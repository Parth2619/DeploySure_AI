function money(n) { return "$" + Number(n).toFixed(2); }

async function getQuote() {
  const error = document.getElementById("error");
  const result = document.getElementById("result");
  error.textContent = "";
  result.textContent = "";
  const price = Number(document.getElementById("price").value);
  const discount = Number(document.getElementById("discount").value);
  const res = await fetch("/api/quote", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ price, discount_percent: discount }),
  });
  if (!res.ok) { error.textContent = "Could not calculate the price"; return; }
  const quote = await res.json();
  result.textContent = `Final price ${money(quote.final_price)} (was ${money(quote.original_price)}, ${quote.discount_percent}% off)`;
}

document.getElementById("quote").addEventListener("click", getQuote);
