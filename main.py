import asyncio
from contextlib import ExitStack
import csv
from pathlib import Path
from textwrap import dedent
from typing import cast, Literal

from bs4 import BeautifulSoup
from bs4.element import Tag
import logfire
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

    def ancestors(self) -> int:
        return sum(r.is_ancestor() for r in self.relations)


mp_relations_ta = TypeAdapter(list[MPRelations])

mps_ta = TypeAdapter(list[MP])


async def get_mps(client: AsyncClient) -> list[MP]:
    raw_mps_path = Path('mps.json')
    if raw_mps_path.exists():
        return mps_ta.validate_json(raw_mps_path.read_bytes())

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

    raw_mps_path.write_bytes(mps_ta.dump_json(mps, indent=2))
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
        try:
            while True:
                mp = await queue.get()
                # debug(mp)
                if any(mp.id == r.id for r in mp_relations):
                    queue.task_done()
                    progress.update(extract_task, advance=1)
                    continue

                html = await get_html(client, mp.url)
                soup = BeautifulSoup(html, 'html.parser')

                body = soup.find(id='mw-content-text')
                assert body is not None, f'Could not find body element in {mp.url}'

                r = await agent.run(body.text)
                mp_relations.append(MPRelations(**mp.model_dump(), relations=r.data))

                queue.task_done()
                progress.update(extract_task, advance=1)
        except Exception as e:
            print(f'Worker error: {e}')
            raise

    with Progress() as progress:
        extract_task = progress.add_task('Extracting relations...', total=len(raw_mps))

        raw_mps = mps_ta.validate_json(Path('mps.json').read_bytes())
        queue: asyncio.Queue[MP] = asyncio.Queue()

        for mp in raw_mps:
            queue.put_nowait(mp)

        try:
            tasks = [asyncio.create_task(extract_worker(queue)) for _ in range(20)]
            await queue.join()
            for task in tasks:
                task.cancel()
        finally:
            if mp_relations:
                mp_relations_path.write_bytes(mp_relations_ta.dump_json(mp_relations, indent=2))

    return mp_relations


def write_csv(mp_relations: list[MPRelations]):
    path = Path('mp_relations.csv')
    with path.open('w', newline='') as csvfile:
        fieldnames = list(MP.model_fields.keys()) + ['party', 'relations', 'ancestors']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()
        for mp in mp_relations:
            d = mp.model_dump(exclude={'relations'})
            d.update(
                relations=len(mp.relations),
                ancestors=mp.ancestors(),
            )
            writer.writerow({k: str(v) for k, v in d.items()})


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
    write_csv(mp_relations)


if __name__ == '__main__':
    asyncio.run(main())
