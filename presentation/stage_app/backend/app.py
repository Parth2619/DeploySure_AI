"""PriceRight backend: a discount calculator. Demo target for DeploySure, dummy data only."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import pricing

app = FastAPI(title="PriceRight")


class QuoteIn(BaseModel):
    price: float
    discount_percent: float


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/quote")
def quote(body: QuoteIn) -> dict:
    try:
        final = pricing.apply_discount(body.price, body.discount_percent)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
    if final < 0:  # a shop must never show a negative price, so this is a server fault
        raise HTTPException(status_code=500, detail="pricing returned a negative price")
    return {"original_price": body.price, "discount_percent": body.discount_percent, "final_price": final,
            "savings": round(body.price - final, 2)}


# Mounted last so the API routes above win.
app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[1] / "frontend", html=True), name="frontend")
