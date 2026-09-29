"""The AgentAdapter interface every concrete adapter implements.

Per the locked audit (§6, final V1 decision): exactly two concrete
adapters ship in this phase — HTTPAdapter and LocalAdapter — both behind
this one interface, so every later phase (the Suite Runner especially)
invokes an agent the same way regardless of connection type.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.adapters.execution import AgentExecution


class AgentAdapter(ABC):
    """Invokes a System Under Test and returns a normalized
    AgentExecution. Implementations must never raise for a failed/timed
    -out invocation of the agent itself — that outcome is data
    (AgentExecution(status="error"/"timeout")), not an exception. They
    may raise AdapterConfigError, but only for a configuration problem
    detected before the agent is ever invoked (see exceptions.py).
    """

    @abstractmethod
    async def invoke(self, input: dict[str, Any]) -> AgentExecution:
        raise NotImplementedError
