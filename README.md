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
