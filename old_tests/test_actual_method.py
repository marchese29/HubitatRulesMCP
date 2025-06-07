import asyncio
import os
from hubitat import HubitatClient


async def test_device_by_id():
    """Test the actual device_by_id method with real API call."""

    # Set the environment variables based on the provided URL
    os.environ["HE_ADDRESS"] = "10.0.0.205"
    os.environ["HE_APP_ID"] = "257"
    os.environ["HE_ACCESS_TOKEN"] = "201f1e65-f148-4567-ab1d-7beff56f97a2"

    # Create the client and call the method
    client = HubitatClient()

    print("Testing device_by_id method with device ID 64...")

    try:
        device = await client.device_by_id(64)

        print("\n✓ Method executed successfully!")
        print(f"✓ Device ID: {device.id} (type: {type(device.id).__name__})")
        print(f"✓ Device Name: {device.name}")
        print(f"✓ Number of attributes: {len(device.attributes)}")
        print(f"✓ Number of commands: {len(device.commands)}")

        print("\nAttributes:")
        for attr_name in sorted(device.attributes):
            print(f"  - {attr_name}")

        print(f"\nCommands: {sorted(device.commands)}")

        # Verify the types are correct
        assert isinstance(device.id, int), (
            f"Expected int for device.id, got {type(device.id)}"
        )
        assert isinstance(device.name, str), (
            f"Expected str for device.name, got {type(device.name)}"
        )
        assert isinstance(device.attributes, set), (
            f"Expected set for device.attributes, got {type(device.attributes)}"
        )
        assert isinstance(device.commands, set), (
            f"Expected set for device.commands, got {type(device.commands)}"
        )

        print("\n✓ All type validations passed!")
        print(
            "✓ The device_by_id method works correctly and properly converts the API response!"
        )

        return device

    except Exception as e:
        print(f"✗ Error occurred: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(test_device_by_id())
