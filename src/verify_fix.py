import sys
import asyncio
# Because this script is in src, we need to add the parent directory to the path
# for imports like 'from src.engine...' to work as they do in main.py
sys.path.insert(0, '/app')

from src.engine import Engine
from src.providers.local import LocalProvider
from src.config import load_config

async def main():
    print('--- Starting Verification Script ---')
    try:
        config = load_config()

        print('Step 1: Instantiating the Engine...')
        # Correctly instantiate the engine with only the config
        engine = Engine(config=config)
        print('SUCCESS: Engine instantiated.')

        print('\nStep 2: Simulating provider creation for \'local\'...')
        # This is the line that was failing
        provider_config_data = config.providers.local
        provider = engine._create_provider('local', provider_config_data)
        print('SUCCESS: _create_provider call for \'local\' did not raise a TypeError.')

        print(f'\nStep 3: Checking the created provider type...')
        assert isinstance(provider, LocalProvider)
        print(f'SUCCESS: Created provider is an instance of LocalProvider.')

        print(f'\nStep 4: Checking if provider implements the contract...')
        assert hasattr(provider, 'supported_codecs')
        print(f'SUCCESS: Provider has the required \'supported_codecs\' property.')

        print('\n--- Verification Complete: The fix is valid. ---')

    except TypeError as e:
        print(f'--- VERIFICATION FAILED: TypeError ---')
        print(f'The application will still crash. Error: {e}')
    except Exception as e:
        print(f'--- VERIFICATION FAILED: Unexpected Error ---')
        print(f'An unexpected error occurred: {e}')
    finally:
        # A shutdown method might not exist if engine init fails, so check first
        if 'engine' in locals() and hasattr(engine, 'stop'):
            await engine.stop()

if __name__ == '__main__':
    asyncio.run(main())
