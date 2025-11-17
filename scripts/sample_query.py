#!/usr/bin/env python3
"""Sample program demonstrating the OMPL RAG assistant."""

from __future__ import annotations

from query_local_rag import run_query


def main() -> None:
    question = "OMPLの最適化プランナーはどのような目的関数を扱える？"
    context, answer = run_query(question)
    print("# Question")
    print(question)
    print("\n# Retrieved Context")
    print(context)
    print("\n# Answer")
    print(answer)


if __name__ == "__main__":
    main()
