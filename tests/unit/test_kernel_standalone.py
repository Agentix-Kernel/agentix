"""Boundary smoke test — the kernel imports and runs with NO app on the path.

Importing the kernel's public surface must not pull in any ``ludo`` (app) module,
nor the generated wire packages (``ludo_shared`` / ``ludo_internal`` — cluster
vendoring machinery, not kernel dependencies). This is the runtime complement to
``test_kernel_purity`` (which checks the source): together they prove Agentix
stands alone as a reusable, brand-free package.
"""

from __future__ import annotations

import sys


def test_importing_kernel_pulls_in_no_app_module() -> None:
    # Exercise the public surface an app depends on.
    import agentix  # noqa: F401
    from agentix.config import KernelConfig  # noqa: F401
    from agentix.core.agent_dispatcher import AgentDispatcher, DispatchGuard, TerminationPolicy  # noqa: F401
    from agentix.core.engine import Engine  # noqa: F401
    from agentix.core.session import Session, create_session  # noqa: F401
    from agentix.llm.router import ProviderRouter  # noqa: F401
    from agentix.storage import MinioStore, SqliteStore  # noqa: F401
    from agentix.tools.safety import SafetyGate  # noqa: F401

    # No app module should have been imported as a side effect — neither the
    # app package (ludo.*) nor the generated wire packages the repo vendors out.
    app_modules = [m for m in sys.modules if m == "ludo" or m.startswith(("ludo.", "ludo_shared", "ludo_internal"))]
    assert app_modules == [], f"kernel import leaked app modules: {app_modules}"


def test_kernel_version_is_exposed() -> None:
    import agentix

    assert isinstance(agentix.__version__, str) and agentix.__version__
