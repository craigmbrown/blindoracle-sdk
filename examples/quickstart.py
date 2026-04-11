"""BlindOracle SDK — Quick Start Examples"""

from blindoracle_sdk import BlindOracleClient

# ── 1. Free tier — no API key ──────────────────────────────────────────────
client = BlindOracleClient()

markets = client.markets.list(status="active", limit=5)
print(f"Active markets: {len(markets)}")
for m in markets:
    print(f"  {m.title}: P(yes)={m.yes_probability}")

# ── 2. With API key ────────────────────────────────────────────────────────
client = BlindOracleClient(api_key="bo_live_your_key_here")

# DeFi compliance check
result = client.compliance.check("aave-v3")
print(f"\nAave-v3 risk: {result.risk_score}/100 (tail risk: {result.tail_risk_pct}%)")

# Latest signal
signal = client.signals.latest(category="defi")
print(f"\nSignal: [{signal.signal_type}] {signal.title} ({signal.confidence:.0%} confidence)")

# ── 3. LangChain agent ────────────────────────────────────────────────────
# pip install blindoracle-sdk[langchain] langchain-openai
#
# from blindoracle_sdk.integrations.langchain_tools import get_blindoracle_tools
# from langchain.agents import initialize_agent, AgentType
# from langchain_openai import ChatOpenAI
#
# tools = get_blindoracle_tools(api_key="bo_live_...")
# agent = initialize_agent(tools, ChatOpenAI(), agent=AgentType.OPENAI_FUNCTIONS)
# result = agent.run("What DeFi protocols have elevated risk today?")
# print(result)

# ── 4. CrewAI ─────────────────────────────────────────────────────────────
# pip install blindoracle-sdk[crewai]
#
# from blindoracle_sdk.integrations.crewai_tools import blindoracle_compliance_check
# from crewai import Agent, Task, Crew
#
# analyst = Agent(
#     role="DeFi Risk Analyst",
#     goal="Identify DeFi protocol risk",
#     tools=[blindoracle_compliance_check],
# )
# task = Task(description="Check Aave-v3 compliance risk", agent=analyst)
# crew = Crew(agents=[analyst], tasks=[task])
# crew.kickoff()
