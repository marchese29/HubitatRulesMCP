"""Test script to verify device loading functionality."""

import asyncio
import os

# Set environment variables from the provided URL
os.environ["HE_ADDRESS"] = "10.0.0.205"
os.environ["HE_APP_ID"] = "257"
os.environ["HE_ACCESS_TOKEN"] = "201f1e65-f148-4567-ab1d-7beff56f97a2"

from hubitat import HubitatClient
from rules.interface import Device


async def test_device_loading():
    """Test the new device loading functionality."""
    print("Testing Device loading functionality...")

    # Create client and device
    client = HubitatClient()
    device = Device(device_id=64, he_client=client)

    # Test 1: Accessing attribute before loading should fail
    print("\n1. Testing access before loading (should fail)...")
    try:
        _ = device.temperature  # This should raise an error
        print("❌ ERROR: Should have failed but didn't!")
    except RuntimeError as e:
        print(f"✅ Expected error: {e}")

    # Test 2: Load the device
    print("\n2. Loading device...")
    loaded_device = await device.load()
    print(f"✅ Device loaded successfully: {loaded_device is device}")

    # Test 3: Access attributes after loading
    print("\n3. Testing access after loading...")
    try:
        # Try to access an attribute (this will create an Attribute object)
        door_attr = device.door
        print(f"✅ Successfully accessed door attribute: {type(door_attr)}")

        # Try to access another attribute
        contact_attr = device.contact
        print(f"✅ Successfully accessed contact attribute: {type(contact_attr)}")

        # Try to access a command (this will create a Command object)
        open_command = device.open
        print(f"✅ Successfully accessed open command: {type(open_command)}")

        # Try to access another command
        close_command = device.close
        print(f"✅ Successfully accessed close command: {type(close_command)}")

    except Exception as e:
        print(f"❌ Error accessing device after loading: {e}")

    print("\n🎉 All tests completed!")


if __name__ == "__main__":
    asyncio.run(test_device_loading())
