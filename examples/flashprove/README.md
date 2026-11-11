# Check a proof of inference yourself (FlashProve)

[FlashProve](https://github.com/anthropics/FlashProve) (Anthropic, Apache 2.0, released 2026-11-02)
lets a model provider prove that a reply came from the weights behind a published **commitment
ID**, without revealing the weights. The provider proves on a GPU. Anyone checks on a CPU.

`verify_inference_proof.py` wraps FlashProve's own verifier, `cp_verify`, and returns one JSON
verdict. It adds no cryptography and makes no network call. It also does not call BlindOracle.

## What we ran (2026-11-11)

FlashProve v0.16.0 at commit `9e2bdd8ff5bf9c62f18263d7dac189b0400b260c`, built with g++ 12.2.
FlashProve supports g++ 13 and up, but 12.2 built it and passed the selftest. The machine was a 4-core cloud VM with 15 GB of RAM and no GPU.

| Case | Expected | Got | Time |
|---|---|---|---|
| `accepted-proof` (small model, synthetic weights) | accepted | `YES` | ~3 s |
| `accepted-proof-clipped-gap` | accepted | `WITHIN LIMITS` | <1 s |
| `full-size` (Llama 4 Maverick shape, synthetic weights) | accepted | `YES` | ~32 s |
| `full-size-clipped-gap` | accepted | `WITHIN LIMITS` | ~1 s |
| one byte of the proof flipped | refused | `NO: proof-refused` | |
| wrong commitment ID | refused | `NO: model-statement` | |
| a different reply token | refused | `NO: reply-differs` | |

## Run it

```sh
git clone https://github.com/anthropics/FlashProve && cd FlashProve
git checkout 9e2bdd8ff5bf9c62f18263d7dac189b0400b260c
verifier/build.sh                       # 1-2 min; last line: THE VERIFIER IS BUILT
python3 /path/to/verify_inference_proof.py --flashprove-dir . --selftest   # ~2 min
```

To check a real proof, use the commitment ID from a party you trust:

```sh
python3 verify_inference_proof.py --flashprove-dir ./FlashProve \
  --config CONFIG_DIR --ivk PUBLIC_KEY_DIR --request REQ --tokens Y --proof PROOF \
  --id <64-hex commitment ID>
```

The exit code is 0 when the proof is accepted, 1 when it is refused, and 2 when there is no verdict.
A proof counts as accepted only when `cp_verify` exits with 0 **and** its last line is `YES` or `WITHIN LIMITS: …`.
Any other combination is reported as no verdict.

## The one rule

Get the commitment ID from a party you trust. **Never** take it from the server whose reply you are
checking, or from files that came with the proof. A valid proof says only that the weights behind
this ID produced this reply. If the same server handed you the ID, a valid proof tells you
nothing about which model ran.

## What a YES does not tell you

- that the provider serves the same weights to every user, or for replies that were not proved;
- anything about the model's safety or quality;
- anything outside FlashProve v0.16.0's scope: Llama 4 Maverick's architecture, greedy decoding,
  and contexts up to 1,024 tokens.

## Status, 2026-11-11

We know of **no provider that publishes a FlashProve commitment ID for a model it serves**.
The only public IDs are the four synthetic examples above. If you publish one, open an issue on
this repository. We will check your sample proofs with this script and publish the exact
commands and results.
