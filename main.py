from typing import Union

from fastapi import FastAPI
from implementations import IMPLEMENTATIONS
from interop import InteropRunner
from pydantic import BaseModel

app = FastAPI()


class InteropConfig(BaseModel):
    name: str
    description: str | None = None
    price: float
    tax: float | None = None


implementations = {
    name: {"image": value["image"], "url": value["url"]}
    for name, value in IMPLEMENTATIONS.items()
}


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.post("/run")
def run_interop():
    return InteropRunner(
        implementations=implementations,
        servers=["quiche"],
        clients=["quiche"],
        tests=[],
        measurements=["goodput"],
        output="output.json",
        debug=True,
        log_dir="",
        save_files=False,
    ).run()
