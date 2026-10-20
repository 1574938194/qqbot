import asyncio
import tempfile
from pathlib import Path

from qqbot.config import Settings
from qqbot.store import Store
from qqbot.tasks import Tasks


async def main():
    with tempfile.TemporaryDirectory() as directory:
        store = Store(str(Path(directory) / 'web.db'))
        tasks = Tasks(store, None, Settings.load())
        try:
            body, url = await tasks.tools.fetch('https://www.python.org/')
            print('web_fetch PASS, chars=' + str(len(body)))
            result = await tasks.tools.search('Python official documentation')
            print('web_search PASS, chars=' + str(len(result)))
        finally:
            await tasks.close()
            store.close()


if __name__ == '__main__':
    asyncio.run(main())
