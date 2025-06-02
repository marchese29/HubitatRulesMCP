from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from hubitat import HubitatClient


mcp = FastMCP(name="Hubitat Rules")


# Common Resources
he_client = HubitatClient()


@mcp.custom_route("/", methods=["GET"])
async def hello_world(request: Request) -> PlainTextResponse:
    return PlainTextResponse("Hello, World!")


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8080)
