---
title: How to calculate the real value of an exchange: rate, fees, reserve
description: Why the top rate in the list isn't always better: how to account for the network and exchanger fees, reserve and limits, and compute the amount you actually receive.
date: 2026-08-24
slug: realnaya-vygoda-obmena
---

# How to calculate the real value of an exchange

A common mistake is picking an exchanger by the top-line rate alone. The final amount you receive is made up
of several things, and sometimes the second or third exchanger in the list is better than the first. Let's
count honestly.

## What the final amount consists of

**Amount received = (amount × rate) − network fee − exchanger fee.**

- **Rate** — how many units of the received currency you get per unit of the sent one.
- **[Network fee](/en/blog/komissii-setey-tron-eth-bsc/)** (for crypto) — the blockchain's charge for a
  transfer; depends on the network and load. On TRC20 it's tiny, on ERC20 at peak hours it's noticeable.
- **Exchanger fee** — may be built into the rate or charged separately.

## Why the top rate isn't always best

- The exchanger with the best rate may lack the [reserve](/en/faq/) for your amount.
- A high minimum/maximum — your amount doesn't fit the limits.
- The network or service fee "eats" the rate difference.

## The logic in an example

If the rate is 0.3% better but the network fee is higher by more than those 0.3%, the gain is illusory. So
compare not the rate but the **amount received** with all fees, and check the reserve covers your amount.

## Mini calculator

Every currency page in our directory has a [direction calculator](/en/valuta/tether-trc20/): pick a pair and
amount — see an approximate result at the best rate. Then verify the fees in the exchanger itself.

## Checklist

- [ ] counted the amount received, not just the rate;
- [ ] included the network fee (for crypto) and the exchanger fee;
- [ ] reserve covers the amount, it's within limits;
- [ ] exchanger has a rating ([how to choose](/en/blog/kak-vybrat-obmennik/)).

## In short

- Compare the amount received, not the top rate.
- Network and exchanger fees change the picture.
- Reserve and limits are part of the value.

Rates for all currencies — in the [directory](/en/).
