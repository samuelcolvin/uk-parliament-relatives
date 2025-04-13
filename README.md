# Members of UK Parliament with Political Relations

As discussed on The Rest is Politics last week.

## Methodology

* Get a list of current MPs from [here](https://en.wikipedia.org/wiki/List_of_MPs_elected_in_the_2024_United_Kingdom_general_election)
* Go through each wikipedia page and use [PydanticAI](https://ai.pydantic.dev) with GPT 4o (although other models will probably perform equally well) to find and extract a any relations to the PM who are or were politically active
* Summarize the results

Full details for each MP can be seen in [`mp_relations.json`](mp_relations.json).

Results across all parties ("ancestor" means parent, grandparent, uncle, aunt e.g. not siblings or spouses):

| political_ancestor_percentage | political_relations_percentage | mps |
| ---                           | ---                            | --- |
| f64                           | f64                            | u32 |
|-------------------------------|--------------------------------|-----|
| 23.69                         | 34.46                          | 650 |

Results per party:

| party            | political_ancestor_percentage | political_relations_percentage | mps |
| ---              | ---                           | ---                            | --- |
| str              | f64                           | f64                            | u32 |
|------------------|-------------------------------|--------------------------------|-----|
| Conservative     | 37.19                         | 44.63                          | 121 |
| Other            | 25.0                          | 36.36                          | 44  |
| Labour           | 20.82                         | 32.2                           | 413 |
| Liberal Democrat | 16.67                         | 29.17                          | 72  |

# How Representative is that

How likely is it that UK members of Parliament are representative of the UK population in terms of ancestor political engagement?

* Average age of an MP [is about](https://commonslibrary.parliament.uk/house-of-commons-trends-the-age-of-mps/) 50.
* UK population in 1975 [was](https://www.macrotrends.net/global-metrics/countries/gbr/united-kingdom/population) 56M.
* Assume there were 20,000 councellors and MPs in 1975 (no idea how accurate that numbers is)
* Assuming two parents with independent changes of being politically active (bad assumption, but how bad?)
* assume each person has 10 ancestors who could have been political (and be included in their wikipedia page)

I think (My statistics are not that good!), the probability of being born with political ancestors is:

```py
population = 56e6
politicians = 20e3
non_politicians = population - politicians
# this is the probability someone is not a politician
prop_not_politicians = non_politicians / population
# probability that all 10 ancestors not a politician
prop_ancestors_not_political = prop_not_politicians ** 10
# probability that at least one ancestor is a politician
prop_ancestors_political = 1 - prop_ancestors_not_political
print(prop_ancestors_political)
#> 0.00356
# number from first table above
politicans_prop_political_ancestors = 0.2369
print(politicans_prop_political_ancestors / prop_ancestors_political)
#> 66.43
```

So by my (potentially wrong!) maths, current MPs are 66x more likely to have political ancestors than the average person.
