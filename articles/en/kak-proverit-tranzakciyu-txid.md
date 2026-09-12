---
title: How to check a crypto transaction by its hash (TxID)
description: What a transaction hash (TxID) is, where to see a transfer's status, how many confirmations are needed and what to do if a transaction is "stuck".
date: 2026-08-27
slug: kak-proverit-tranzakciyu-txid
---

# How to check a transaction by its hash (TxID)

Sent crypto and it "hasn't arrived"? Before panicking — check the transfer's status by its hash. Almost always
the money is fine, it's just going through confirmations.

## What a TxID is

A [transaction hash](/en/slovar/hash-tranzakcii/) (TxID) is a unique identifier of a transfer on the
blockchain. A wallet or exchange gives it right after sending. With a TxID anyone can view the transfer's
details in a network explorer.

## Where to look

In the blockchain explorer of the relevant network (each network has its own). Paste the TxID (or address) —
you'll see the amount, sender/recipient, status and number of [confirmations](/en/slovar/podtverzhdenie/).

## What the status means

- **Pending** — the transaction is accepted but not yet in a block. Wait.
- **Confirmed** — included in a block; the more confirmations, the more reliable.
- **Failed** — didn't go through (e.g., insufficient fee). Funds usually stay with the sender.

## How many confirmations are needed

Depends on the network and recipient. Exchangers and exchanges usually wait for several before crediting —
protection against a reversed transfer. While there are few, funds are «in transit».

## If a transaction is "stuck"

- Check the status by TxID — most often it's a confirmation queue.
- A low [network fee](/en/slovar/komissiya-seti/) can slow a transfer in a busy network.
- If the status is Failed — funds weren't deducted; retry with a correct fee.

## In short

- The TxID is a transfer's «tracking number»; it shows status in a network explorer.
- Wait for confirmations — that's normal, not lost money.
- Failed = funds with the sender; Pending = in transit.

Network and transaction terms — in the [glossary](/en/slovar/). Rates — in the [directory](/en/).
