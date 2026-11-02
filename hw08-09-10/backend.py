"""Injectable backends. Importing the stub never imports model libraries."""
import time
from pathlib import Path
from release import digest, canonical, verify_artifact


class StubBackend:
    def __init__(self, manifest, root):
        verify_artifact(manifest, root)
        self.loaded_id = manifest['model_id']
        self.runtime_sha256 = manifest['runtime_sha256']
        self.calls = 0
        self.limit = manifest['runtime']['generation']['max_new_tokens']
        self.fixed_limit = False

    def warmup(self):
        pass

    def generate(self, prompt, limit):
        self.calls += 1
        time.sleep(.01)
        return {'answer': f'STUB ONLY: {self.loaded_id}', 'output_tokens': 1, 'input_tokens': len(prompt.split())}


class TransformersBackend:
    def __init__(self, manifest, root):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        if manifest.get('synthetic') or manifest['runtime']['base_revision'] == 'fixture-only':
            raise ValueError('A synthetic release cannot load a real backend')
        artifact = verify_artifact(manifest, root)
        runtime = manifest['runtime']
        if len(runtime['base_revision']) != 40:
            raise ValueError('Base revision must be pinned')
        torch.set_num_threads(4)
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(artifact, local_files_only=True)
        tokenizer_files = {name: manifest['file_hashes'][name] for name in manifest['tokenizer_files']}
        if digest(canonical(tokenizer_files)) != runtime['tokenizer_sha256']:
            raise ValueError('Tokenizer identity mismatch')
        if digest(self.tokenizer.chat_template.encode()) != runtime['template_sha256']:
            raise ValueError('Chat template identity mismatch')
        base_path = artifact if manifest['model_kind'] == 'base' else Path(manifest['base_artifact_uri'])
        self.model = AutoModelForCausalLM.from_pretrained(base_path, local_files_only=True,
                                                        dtype=getattr(torch, runtime['dtype'])).to('cpu').eval()
        if manifest['model_kind'] == 'adapter':
            from peft import PeftModel
            self.model = PeftModel.from_pretrained(self.model, artifact).eval()
        self.runtime = runtime
        self.loaded_id = manifest['model_id']
        self.runtime_sha256 = manifest['runtime_sha256']
        self.limit = runtime['generation']['max_new_tokens']
        self.fixed_limit = True
        self.calls = 0

    def warmup(self):
        self.generate('Say hello.', self.limit)

    def generate(self, prompt, limit):
        g = self.runtime['generation']
        text = self.tokenizer.apply_chat_template(
            [{'role': 'system', 'content': g['system']}, {'role': 'user', 'content': prompt}],
            tokenize=False, add_generation_prompt=True, enable_thinking=g['enable_thinking'])
        batch = self.tokenizer(text, return_tensors='pt')
        if batch['input_ids'].shape[1] > 2048:
            raise ValueError('Input exceeds 2048 tokens including system/template')
        if limit != self.limit:
            raise ValueError('Generation limit differs from the evaluated protocol')
        self.calls += 1
        if g['do_sample']:
            self.torch.manual_seed(g['seed'])
        with self.torch.inference_mode():
            output = self.model.generate(**batch, max_new_tokens=limit, do_sample=g['do_sample'],
                pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id)
        tokens = output[0, batch['input_ids'].shape[1]:]
        return {'answer': self.tokenizer.decode(tokens, skip_special_tokens=True),
                'output_tokens': len(tokens), 'input_tokens': batch['input_ids'].shape[1]}
