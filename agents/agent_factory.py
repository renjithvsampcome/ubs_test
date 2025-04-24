import autogen
from typing import List, Dict, Any, Optional
import logging
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get API keys and configurations from environment
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

logger = logging.getLogger(__name__)

def create_agent_system():
    """Creates and configures the multi-agent system for alert processing"""
    
    # Configuration for the LLM
    llm_config = {
        "temperature": 0.2,
        "api_key": OPENAI_API_KEY,
        "model": OPENAI_MODEL
    }
    
    # Create the market compliance agent
    market_validator_agent = autogen.AssistantAgent(
        name="MarketValidatorAgent",
        system_message="""You are a financial market validator agent specializing in determining 
        if a security is traded on a regulated market or growth market. You check German and French 
        market information based on ISIN numbers. For Germany, check if it's "Regulierter Markt" (regulated) 
        or other markets. For France, check if it's "Marché réglementé" (regulated) or "Marché de croissance" (growth).""",
        llm_config=llm_config,
    )
    
    # Create the outstanding shares validator agent
    shares_validator_agent = autogen.AssistantAgent(
        name="SharesValidatorAgent",
        system_message="""You are an outstanding shares validation agent. You compare the number of 
        outstanding shares in the UBS system with the information from commercial registers. If there's a 
        discrepancy between the values, it indicates a false positive. Be precise with number comparisons.""",
        llm_config=llm_config,
    )
    
    # Create the evidence collector agent
    evidence_collector_agent = autogen.AssistantAgent(
        name="EvidenceCollectorAgent", 
        system_message="""You are an evidence collection agent responsible for taking snapshots of 
        webpages that provide evidence for decision-making. You create PDF snapshots of relevant pages
        and ensure they're timestamped for audit purposes.""",
        llm_config=llm_config,
    )
    
    # Create the decision making agent
    decision_agent = autogen.AssistantAgent(
        name="DecisionAgent",
        system_message="""You are a decision-making agent for UBS Compliance. You analyze inputs from 
        validator agents to determine if an alert is a true positive (requiring regulatory reporting) or 
        a false positive. You provide clear justifications for each decision, summarizing the evidence collected.""",
        llm_config=llm_config,
    )
    
    # Create a human-in-the-loop agent for oversight
    human_agent = autogen.UserProxyAgent(
        name="HumanOversight",
        human_input_mode="NEVER",
        is_termination_msg=lambda msg: "APPROVED" in msg.get("content", ""),
        code_execution_config={"use_docker": False},
    )
    
    # Create the group chat for the agents to collaborate
    groupchat = autogen.GroupChat(
        agents=[market_validator_agent, shares_validator_agent, evidence_collector_agent, decision_agent, human_agent],
        messages=[],
        max_round=10,
    )
    
    # Create the manager to orchestrate the conversation
    manager = autogen.GroupChatManager(groupchat=groupchat, llm_config=llm_config)
    
    return AgentSystem(
        market_validator=market_validator_agent,
        shares_validator=shares_validator_agent,
        evidence_collector=evidence_collector_agent,
        decision_maker=decision_agent,
        human_agent=human_agent,
        manager=manager
    )

class AgentSystem:
    """Main class that orchestrates the multi-agent system"""
    
    def __init__(self, market_validator, shares_validator, 
                 evidence_collector, decision_maker, human_agent, manager):
        self.market_validator = market_validator
        self.shares_validator = shares_validator
        self.evidence_collector = evidence_collector
        self.decision_maker = decision_maker
        self.human_agent = human_agent
        self.manager = manager
    
    async def process_alert(self, alert):
        from models.alert_models import AlertProcessingResult
        
        try:
            logger.info(f"Processing alert {alert.alert_id}")
            
            # Create the message for the group chat
            message = f"""
            Process the following alert for UBS Compliance:
            - Alert ID: {alert.alert_id}
            - ISIN: {alert.isin}
            - Security Name: {alert.security_name}
            """
            
            if alert.outstanding_shares_system:
                message += f"- Outstanding Shares in System: {alert.outstanding_shares_system}\n"
            
            message += """
            Steps:
            1. MarketValidatorAgent: Check if this security is traded on a regulated market or growth market
            2. SharesValidatorAgent: Verify outstanding shares information if available
            3. EvidenceCollectorAgent: Collect screenshots of relevant pages as evidence
            4. DecisionAgent: Make a final decision whether this is a true or false positive
            
            Please proceed with the analysis.
            """
            
            # Option 1: Send message via human agent
            self.human_agent.initiate_chat(self.manager, message=message)
            # Get chat history
            result = self.human_agent.chat_messages[self.manager]
            
            # Extract the final decision from the chat
            decision_message = self._extract_decision(result)
            
            # Parse the decision
            is_true_positive = "true positive" in decision_message.lower()
            justification = self._extract_justification(decision_message)
            evidence_url = self._extract_evidence_url(result)
            
            return AlertProcessingResult(
                alert_id=alert.alert_id,
                is_true_positive=is_true_positive,
                justification=justification,
                evidence_url=evidence_url,
                evidence_path=None  # Will be populated after PDF generation
            )
            
        except Exception as e:
            logger.error(f"Error in agent processing: {e}", exc_info=True)
            return AlertProcessingResult(
                alert_id=alert.alert_id,
                is_true_positive=False,
                justification=f"Processing error: {str(e)}",
                evidence_url=None,
                evidence_path=None
            )
    
    def _extract_decision(self, chat_result):
        """Extract the final decision from the chat results"""
        # Find the last message from the decision agent
        for message in reversed(chat_result):
            if message.get("sender") == "DecisionAgent":
                return message.get("content", "")
        return ""
    
    def _extract_justification(self, decision_message):
        """Extract the justification from the decision message"""
        # Simple extraction - would be more sophisticated in production
        if "justification:" in decision_message.lower():
            parts = decision_message.lower().split("justification:")
            if len(parts) > 1:
                return parts[1].strip()
        return decision_message
    
    def _extract_evidence_url(self, chat_result):
        """Extract the evidence URL from the chat results"""
        for message in reversed(chat_result):
            if message.get("sender") == "EvidenceCollectorAgent":
                content = message.get("content", "")
                if "http" in content:
                    # Extract URL - simplified extraction
                    for word in content.split():
                        if word.startswith("http"):
                            return word
        return None