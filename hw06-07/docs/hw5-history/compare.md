# Базовая модель против адаптера

Адаптер: `models/adapter_all_layers`. Генерация жадная, до 40 токенов.

## 1. Article: Tucson,_Arizona
Passage: Tucson (/ˈtuːsɒn/ /tuːˈsɒn/) is a city and the county seat of Pima County, Arizona, United States, and home to the University of Arizona. The 2010 United States Census put the population at 520,116, while the 2013 estimated population of the entire Tucson metropolitan statistical area (MSA) was 996,544. The Tucson MSA forms part of the larger Tucson-Nogales combined statistical area (CSA), with a total population of 980,263 as of the 2010 Census. Tucson is the second-largest populated city in Arizona behind Phoenix, both of which anchor the Arizona Sun Corridor. The city is  located 108 miles (174 km) southeast of Phoenix and 60 mi (97 km) north of the U.S.-Mexico border. Tucson is the 33rd largest city and the 59th largest metropolitan area in the United States. Roughly 150 Tucson companies are involved in the design and manufacture of optics and optoelectronics systems, earning Tucson the nickname Optics Valley.
Question: What is the largest populated city in Arizona?

**База:**

> The largest populated city in Arizona is Phoenix.

**Адаптер:**

> Phoenix

## 2. Article: Tucson,_Arizona
Passage: Tucson (/ˈtuːsɒn/ /tuːˈsɒn/) is a city and the county seat of Pima County, Arizona, United States, and home to the University of Arizona. The 2010 United States Census put the population at 520,116, while the 2013 estimated population of the entire Tucson metropolitan statistical area (MSA) was 996,544. The Tucson MSA forms part of the larger Tucson-Nogales combined statistical area (CSA), with a total population of 980,263 as of the 2010 Census. Tucson is the second-largest populated city in Arizona behind Phoenix, both of which anchor the Arizona Sun Corridor. The city is  located 108 miles (174 km) southeast of Phoenix and 60 mi (97 km) north of the U.S.-Mexico border. Tucson is the 33rd largest city and the 59th largest metropolitan area in the United States. Roughly 150 Tucson companies are involved in the design and manufacture of optics and optoelectronics systems, earning Tucson the nickname Optics Valley.
Question: How many miles is Tuscon from the U.S.- Mexico border?

**База:**

> 60 mi (97 km)

**Адаптер:**

> 60 mi

## 3. Article: Tucson,_Arizona
Passage: Tucson (/ˈtuːsɒn/ /tuːˈsɒn/) is a city and the county seat of Pima County, Arizona, United States, and home to the University of Arizona. The 2010 United States Census put the population at 520,116, while the 2013 estimated population of the entire Tucson metropolitan statistical area (MSA) was 996,544. The Tucson MSA forms part of the larger Tucson-Nogales combined statistical area (CSA), with a total population of 980,263 as of the 2010 Census. Tucson is the second-largest populated city in Arizona behind Phoenix, both of which anchor the Arizona Sun Corridor. The city is  located 108 miles (174 km) southeast of Phoenix and 60 mi (97 km) north of the U.S.-Mexico border. Tucson is the 33rd largest city and the 59th largest metropolitan area in the United States. Roughly 150 Tucson companies are involved in the design and manufacture of optics and optoelectronics systems, earning Tucson the nickname Optics Valley.
Question: What nickname does Tuscon have because of their many companies involved in optics?

**База:**

> Optics Valley

**Адаптер:**

> Optics Valley

## 4. Article: Tucson,_Arizona
Passage: Tucson (/ˈtuːsɒn/ /tuːˈsɒn/) is a city and the county seat of Pima County, Arizona, United States, and home to the University of Arizona. The 2010 United States Census put the population at 520,116, while the 2013 estimated population of the entire Tucson metropolitan statistical area (MSA) was 996,544. The Tucson MSA forms part of the larger Tucson-Nogales combined statistical area (CSA), with a total population of 980,263 as of the 2010 Census. Tucson is the second-largest populated city in Arizona behind Phoenix, both of which anchor the Arizona Sun Corridor. The city is  located 108 miles (174 km) southeast of Phoenix and 60 mi (97 km) north of the U.S.-Mexico border. Tucson is the 33rd largest city and the 59th largest metropolitan area in the United States. Roughly 150 Tucson companies are involved in the design and manufacture of optics and optoelectronics systems, earning Tucson the nickname Optics Valley.
Question: What was the population of Tuscon according to the 2010 U.S. Census? 

**База:**

> 520,116

**Адаптер:**

> 520,116

## 5. Article: Tucson,_Arizona
Passage: Tucson (/ˈtuːsɒn/ /tuːˈsɒn/) is a city and the county seat of Pima County, Arizona, United States, and home to the University of Arizona. The 2010 United States Census put the population at 520,116, while the 2013 estimated population of the entire Tucson metropolitan statistical area (MSA) was 996,544. The Tucson MSA forms part of the larger Tucson-Nogales combined statistical area (CSA), with a total population of 980,263 as of the 2010 Census. Tucson is the second-largest populated city in Arizona behind Phoenix, both of which anchor the Arizona Sun Corridor. The city is  located 108 miles (174 km) southeast of Phoenix and 60 mi (97 km) north of the U.S.-Mexico border. Tucson is the 33rd largest city and the 59th largest metropolitan area in the United States. Roughly 150 Tucson companies are involved in the design and manufacture of optics and optoelectronics systems, earning Tucson the nickname Optics Valley.
Question: What was the estimated population of the entire Tuscan area in 2013? 

**База:**

> 996,544.

**Адаптер:**

> 996,544
