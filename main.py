import asyncio
from contextlib import ExitStack
import csv
from pathlib import Path
from textwrap import dedent
from typing import cast, Literal

from bs4 import BeautifulSoup
from bs4.element import Tag
import logfire
from polars import DataFrame, Config
from pydantic import BaseModel, TypeAdapter, computed_field
from httpx import AsyncClient
from pydantic_ai import Agent
from rich.progress import Progress

logfire.configure(scrubbing=False, console=False)
logfire.instrument_pydantic_ai()
logfire.instrument_httpx()


class MP(BaseModel):
    id: int
    name: str
    url: str
    raw_party: str

    @computed_field
    @property
    def party(self) -> Literal['Conservative', 'Labour', 'Liberal Democrat', 'Other']:
        raw_party = self.raw_party.lower()
        if 'conservative' in raw_party:
            return 'Conservative'
        elif 'labour' in raw_party:
            return 'Labour'
        elif 'liberal democrat' in raw_party:
            return 'Liberal Democrat'
        else:
            return 'Other'


mps_ta = TypeAdapter(list[MP])


class PoliticalRelation(BaseModel, use_attribute_docstrings=True):
    """Family member who was either a member of parliament a local councilor, or otherwise a politician."""

    name: str
    """Name of the family member"""
    role: str
    """Political role of the family member"""
    relation: Literal['father', 'mother', 'uncle', 'aunt', 'husband', 'grandparent etc.', 'wife', 'brother', 'sister']
    """Relationship of the family member to the politician"""
    party: str | None = None
    """Political party of the family member"""

    def is_ancestor(self) -> bool:
        return self.relation in {'father', 'mother', 'uncle', 'aunt', 'grandparent etc.'}


class MPRelations(MP):
    relations: list[PoliticalRelation]

    @computed_field
    @property
    def political_relations_count(self) -> int:
        return len(self.relations)

    @computed_field
    @property
    def political_ancestor_count(self) -> int:
        return sum(r.is_ancestor() for r in self.relations)


mp_relations_ta = TypeAdapter(list[MPRelations])

mps_ta = TypeAdapter(list[MP])


async def get_mps(client: AsyncClient) -> list[MP]:
    html = await get_html(
        client, 'https://en.wikipedia.org/wiki/List_of_MPs_elected_in_the_2024_United_Kingdom_general_election'
    )

    soup = BeautifulSoup(html, 'html.parser')
    mps_table = soup.find(id='elected-mps')
    assert isinstance(mps_table, Tag), 'Table not found'
    table_body = mps_table.find('tbody')
    assert isinstance(table_body, Tag), 'Table body not found'
    mps: list[MP] = []
    for i, row in enumerate(table_body.find_all('tr')):
        assert isinstance(row, Tag), 'Row not found'
        cells = cast(list[Tag], row.find_all('td'))
        if len(cells) > 5:
            mp_a = cells[3].find_all('a')[-1]
            assert isinstance(mp_a, Tag)
            path = mp_a['href']
            assert path, 'Path not found'
            name = mp_a.text.strip()
            party_a = cells[5].find('a')
            assert isinstance(party_a, Tag), 'Party not found'
            party = party_a['title']
            mp = MP(id=i, name=name, url=f'https://en.wikipedia.org/{path}', raw_party=party)
            mps.append(mp)

    return mps


agent = Agent(
    'openai:gpt-4o',
    result_type=list[PoliticalRelation],
    system_prompt=dedent(
        """
        Your role is to inspect the contents the politician's wikipedia page and extract information
        about any family members who were either a member of parliament a local councilor, or otherwise a politician.
        """
    ),
)


async def extract_relations(client: AsyncClient, raw_mps: list[MP]) -> list[MPRelations]:
    mp_relations_path = Path('mp_relations.json')
    if mp_relations_path.exists():
        mp_relations = mp_relations_ta.validate_json(mp_relations_path.read_bytes())
    else:
        mp_relations = []

    async def extract_worker(queue: asyncio.Queue[MP]):
        while True:
            mp = await queue.get()
            if any(mp.id == r.id for r in mp_relations):
                queue.task_done()
                progress.update(extract_task, advance=1)
                continue

            try:
                html = await get_html(client, mp.url)
                soup = BeautifulSoup(html, 'html.parser')

                body = soup.find(id='mw-content-text')
                assert body is not None, f'Could not find body element in {mp.url}'

                r = await agent.run(body.text)
            except Exception as e:
                print(f'Error extracting relations for {mp}: {e}')
                queue.task_done()
                progress.update(extract_task, advance=1)
                raise
            else:
                mp_relations.append(MPRelations(**mp.model_dump(), relations=r.data))

                queue.task_done()
                progress.update(extract_task, advance=1)

    with Progress() as progress:
        extract_task = progress.add_task('Extracting relations...', total=len(raw_mps))

        raw_mps = mps_ta.validate_json(Path('mps.json').read_bytes())
        queue: asyncio.Queue[MP] = asyncio.Queue()

        for mp in raw_mps:
            queue.put_nowait(mp)

        try:
            tasks = [asyncio.create_task(extract_worker(queue)) for _ in range(12)]
            await queue.join()
            for task in tasks:
                task.cancel()
        finally:
            if mp_relations:
                mp_relations_path.write_bytes(mp_relations_ta.dump_json(mp_relations, indent=2))

    return mp_relations


async def get_html(client: AsyncClient, url: str) -> str:
    r = await client.get(url)
    r.raise_for_status()
    assert r.headers['content-type'].startswith('text/html'), f'Expected HTML content, got {r.headers["content-type"]}'
    return r.text


async def main():
    async with AsyncClient() as client:
        with logfire.span('Getting list of MPs'):
            raw_mps = await get_mps(client)
        with logfire.span('Extracting relations'):
            mp_relations = await extract_relations(client, raw_mps)

    df = DataFrame(
        [
            m.model_dump(include={'name', 'party', 'political_relations_count', 'political_ancestor_count'})
            for m in mp_relations
        ]
    )
    with Config() as cfg:
        cfg.set_tbl_formatting('ASCII_MARKDOWN')
        all_sql = """
select
  round(sum(cast(political_ancestor_count>0 as float)) / count(*) * 100, 2) as political_ancestor_percentage,
  round(sum(cast(political_relations_count>0 as float)) / count(*) * 100, 2) as political_relations_percentage,
  count(*) as mps
from self
"""
        print(df.sql(all_sql))

        party_sql = """
select
  party,
  round(sum(cast(political_ancestor_count>0 as float)) / count(*) * 100, 2) as political_ancestor_percentage,
  round(sum(cast(political_relations_count>0 as float)) / count(*) * 100, 2) as political_relations_percentage,
  count(*) as mps
from self
group by party
order by political_ancestor_percentage desc
"""
        print(df.sql(party_sql))


if __name__ == '__main__':
    asyncio.run(main())
