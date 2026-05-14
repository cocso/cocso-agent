"""cocso_plugin — COCSO 운영 + 도메인 통합 plugin.

4개 sub-module을 한 plugin 으로 묶음:

- ``sandbox``    — SOUL.md / .env / credential 보호 (pre_tool_call block)
- ``audit``      — 세션별 JSONL 감사 로그 + tool-call rate limit
- ``excel``      — Excel (.xlsx) 6 generic tools
- ``settlement`` — COCSO 표준 의약품 정산 수수료 내역서 변환·생성 +
  bundled SKILL

각 sub-module 은 자기 ``register(ctx)`` 를 노출하고, 이 plugin 의
``register(ctx)`` 가 4개를 순차 호출. 한 plugin 으로 묶었지만 책임은
파일 단위로 분리돼 있음 — 어느 sub-module 만 비활성화하려면 해당
파일의 ``register`` 호출을 주석 처리.
"""
from __future__ import annotations

import logging

from . import sandbox, audit, excel, settlement

logger = logging.getLogger(__name__)


def register(ctx) -> None:
    for sub in (sandbox, audit, excel, settlement):
        try:
            sub.register(ctx)
        except Exception as exc:
            # 하나가 깨져도 다른 sub-module 등록은 계속
            logger.warning(
                "cocso_plugin: sub-module %s register failed: %s",
                sub.__name__, exc,
            )
