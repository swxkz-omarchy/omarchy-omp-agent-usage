#!/usr/bin/env python3
"""Record-contract tests for omarchy-agent-usage-omp.

Run with plain python3 - no test framework, no dependencies:

    python3 tests/test_record.py

Every case builds a throwaway session directory and points the collector at
it with PI_CODING_AGENT_DIR, so nothing here reads or writes the real
~/.omp or the real agents panel record. What is being pinned is the panel
contract: which models get which label, what the hero line says, and that no
provider's tokens are lost or merged into another's.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

COLLECTOR = Path(__file__).resolve().parent.parent / "omarchy-agent-usage-omp"
TODAY = dt.datetime.now().date()


def entry(entry_id, provider, model, usage, day=TODAY, role="assistant"):
  stamp = dt.datetime.combine(day, dt.time(12, 0)).isoformat() + "Z"
  return json.dumps({
    "type": "message",
    "id": entry_id,
    "timestamp": stamp,
    "message": {"role": role, "provider": provider, "model": model, "usage": usage},
  })


def run(files, name="session.jsonl.gz"):
  """Collect from a synthetic journal directory and return the record."""
  with tempfile.TemporaryDirectory() as tmp:
    sessions = Path(tmp) / "agent" / "sessions" / "-proj"
    sessions.mkdir(parents=True)
    target = sessions / name
    if name.endswith(".gz"):
      with gzip.open(target, "wt", encoding="utf-8") as handle:
        handle.write("\n".join(files) + "\n")
    else:
      target.write_text("\n".join(files) + "\n", encoding="utf-8")

    env = dict(os.environ, PI_CODING_AGENT_DIR=str(Path(tmp) / "agent"))
    # --print keeps the real panel record untouched; --force skips the cache.
    done = subprocess.run(
      [sys.executable, str(COLLECTOR), "--force", "--print"],
      capture_output=True, text=True, env=env, check=True,
    )
    return json.loads(done.stdout)


def expect(condition, message):
  if not condition:
    raise AssertionError(message)


def test_every_provider_is_counted():
  """A machine on several providers gets one row per provider, not a merge."""
  record = run([
    entry("a1", "anthropic", "claude-opus-4-6", {"input": 100, "output": 50, "cacheRead": 900, "cacheWrite": 10}),
    entry("a2", "openrouter", "claude-opus-4-6", {"input": 200, "output": 25}),
    entry("a3", "openrouter", "openai/gpt-5.5", {"input": 10, "output": 5}),
    entry("a4", "openai-codex", "gpt-5.5", {"input": 7, "output": 3}),
    entry("a5", "google", "gemini-3.1-pro", {"input": 11, "output": 2, "cacheRead": 5, "cacheWrite": 1}),
  ])
  usage = record["modelUsage"]

  # The same model id on two providers is two bills and stays two rows.
  expect("anthropic/claude-opus-4-6" in usage, "anthropic row missing")
  expect("openrouter/claude-opus-4-6" in usage, "openrouter row missing")
  expect(usage["anthropic/claude-opus-4-6"]["inputTokens"] == 100, "anthropic input wrong")
  expect(usage["openrouter/claude-opus-4-6"]["inputTokens"] == 200, "openrouter input wrong")

  # An id only one provider wears keeps its short, familiar label.
  expect("gpt-5.5" in usage, "codex gpt-5.5 row missing")
  expect("openai/gpt-5.5" in usage, "openrouter gpt-5.5 row missing")
  expect("gemini-3.1-pro" in usage, "google row missing")

  expect(record["totalPrompts"] == 5, f"expected 5 turns, got {record['totalPrompts']}")
  expect(record["tierLabel"] == "4 providers", f"tier label was {record['tierLabel']!r}")


def test_native_snake_case_usage_is_read():
  """A provider that reports snake_case must not lose its input and output."""
  record = run([entry(
    "g1", "anthropic", "claude-opus-4-6",
    {"input_tokens": 11, "output_tokens": 2, "cache_read_input_tokens": 5, "cache_creation_input_tokens": 1},
  )])
  bucket = record["modelUsage"]["claude-opus-4-6"]
  expect(bucket["inputTokens"] == 11, f"snake_case input was {bucket['inputTokens']}")
  expect(bucket["outputTokens"] == 2, f"snake_case output was {bucket['outputTokens']}")
  expect(bucket["cacheReadInputTokens"] == 5, f"snake_case cache read was {bucket['cacheReadInputTokens']}")
  expect(bucket["cacheCreationInputTokens"] == 1, f"snake_case cache write was {bucket['cacheCreationInputTokens']}")


def test_aggregate_only_provider_still_counts():
  """A provider reporting one number and nothing else is not dropped."""
  record = run([entry("m1", "some-gateway", "mystery", {"totalTokens": 77})])
  expect(record["modelUsage"]["mystery"]["inputTokens"] == 77, "aggregate-only provider lost")
  expect(record["todayTotalTokens"] == 77, "aggregate-only total wrong")


def test_single_provider_keeps_plain_names():
  """The common case must look exactly like it did before."""
  record = run([
    entry("s1", "openrouter", "stealth/space-bunny-alpha", {"input": 20, "output": 308, "cacheRead": 8384}),
    entry("s2", "openrouter", "thinkingmachines/inkling:free", {"input": 296204, "output": 29308}),
  ])
  expect("stealth/space-bunny-alpha" in record["modelUsage"], "qualified model name was rewritten")
  expect("thinkingmachines/inkling:free" in record["modelUsage"], "second model name was rewritten")
  expect(record["tierLabel"] == "openrouter", f"tier label was {record['tierLabel']!r}")


def test_rewind_and_noise_do_not_double_count():
  """A repeated entry id counts once; user turns and compactions never count."""
  record = run([
    entry("r1", "anthropic", "claude-opus-4-6", {"input": 10, "output": 5}),
    entry("r1", "anthropic", "claude-opus-4-6", {"input": 10, "output": 5}),
    entry("u1", "anthropic", "claude-opus-4-6", {"input": 999}, role="user"),
    json.dumps({"type": "compaction", "id": "k1", "timestamp": "2026-01-01T00:00:00Z"}),
  ])
  expect(record["totalPrompts"] == 1, f"rewind or noise was counted: {record['totalPrompts']}")
  expect(record["todayTotalTokens"] == 15, f"total wrong: {record['todayTotalTokens']}")


def test_older_day_lands_in_its_own_bucket():
  """Days are bucketed by local date, not lumped into today."""
  record = run([
    entry("t1", "anthropic", "claude-opus-4-6", {"input": 1, "output": 1}, day=TODAY - dt.timedelta(days=3)),
    entry("t2", "anthropic", "claude-opus-4-6", {"input": 2, "output": 2}),
  ], name="old.jsonl")
  days = {day["date"]: day["messageCount"] for day in record["recentDays"]}
  expect(days.get((TODAY - dt.timedelta(days=3)).isoformat()) == 2, f"old day missing: {days}")
  expect(record["todayTotalTokens"] == 4, f"today total wrong: {record['todayTotalTokens']}")
  expect(record["activeDays"] == 2, f"active days wrong: {record['activeDays']}")


def test_plain_jsonl_archive_is_read():
  """Both the live and the gzipped journal shape are walked."""
  record = run([entry("g1", "anthropic", "claude-opus-4-6", {"input": 3, "output": 4})], name="session.jsonl")
  expect(record["modelUsage"]["claude-opus-4-6"]["outputTokens"] == 4, "plain jsonl was skipped")


def main() -> int:
  tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
  failures = 0
  for test in tests:
    try:
      test()
      print(f"ok    {test.__name__}")
    except Exception as exc:
      failures += 1
      print(f"FAIL  {test.__name__}: {exc}")
  print(f"\n{len(tests) - failures}/{len(tests)} passed")
  return 1 if failures else 0


if __name__ == "__main__":
  raise SystemExit(main())
