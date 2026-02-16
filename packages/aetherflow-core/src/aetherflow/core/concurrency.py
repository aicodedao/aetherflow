from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, List, Optional, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def run_thread_pool(items: Iterable[T], fn: Callable[[T], R], *, workers: int = 8, fail_fast: bool = True) -> List[R]:
    items = list(items)
    if not items:
        return []

    results: List[Optional[R]] = [None] * len(items)
    errors = []

    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as ex:
        fut_map = {ex.submit(fn, item): idx for idx, item in enumerate(items)}
        for fut in as_completed(fut_map):
            idx = fut_map[fut]
            try:
                results[idx] = fut.result()
            except Exception as e:
                errors.append((idx, e))
                if fail_fast:
                    for f in fut_map:
                        if not f.done():
                            f.cancel()
                    break

    if errors:
        idx, e = errors[0]
        raise RuntimeError(f"ThreadPool task failed at index={idx}: {e}") from e

    return list(results)  # type: ignore
