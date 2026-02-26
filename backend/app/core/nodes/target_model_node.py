import logging
import json
import httpx
import yaml
from typing import Dict, Any, Optional
from langchain_core.prompts import PromptTemplate
from core.config import settings
from core.nodes.shared_resources import llm, strip_think_tags

app_logger = logging.getLogger("uvicorn")

target_model_template = """You are an expert assistant for identifying target models from a configuration.
Given the User Query and the NWC Configuration (which maps articles to their target models/pipelines), identify which article the user is referring to and extract its target model and pipeline.

NWC Configuration:
{nwc_config}

User Query: {question}

Instructions:
1. Find the article in the configuration that best matches the article mentioned in the User Query.
2. Extract the 'model' and 'pipeline' for that article.
3. Return the result in valid JSON format with keys: "article", "model", "pipeline".
4. If the article is not found or ambiguous, return {{"article": null, "model": null, "pipeline": null}}.

Output ONLY JSON.
"""

def fetch_nwc_config(auth_token: str) -> Dict[str, Any]:
    if not auth_token:
        app_logger.warning("fetch_nwc_config: No auth token provided")
        return {}
    
    url = f"{settings.nwc_service_url}/config"
    headers = {"Authorization": f"Bearer {auth_token}"}
    
    try:
        app_logger.info(f"fetch_nwc_config: Requesting {url}")
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=headers)
            app_logger.info(f"fetch_nwc_config: Response Status: {resp.status_code}")
            
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError:
                    app_logger.info("fetch_nwc_config: Response is not JSON, trying YAML")
                    return yaml.safe_load(resp.text)
            else:
                app_logger.error(f"fetch_nwc_config: Error {resp.status_code}: {resp.text}")
                return {}
    except Exception as e:
        app_logger.error(f"fetch_nwc_config: Exception: {e}", exc_info=True)
        return {}

def target_model_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Node that loads the NWC config and uses LLM to extract the target model 
    for the article mentioned in the query.
    Safe node (does not trigger confirmation).
    """
    question = state.get("question", "")
    auth_token = state.get("auth_token")
    
    app_logger.info(f"target_model_node: processing question '{question}'")
    
    # 1. Fetch Config
    config = fetch_nwc_config(auth_token)
    model_article = config.get("model_article", {})
    config_str = json.dumps(model_article, ensure_ascii=False, indent=2)
    
    # 2. Call LLM to extract info
    prompt = PromptTemplate.from_template(target_model_template)
    chain = prompt | llm
    
    try:
        response = chain.invoke({
            "nwc_config": config_str,
            "question": question
        })
        content = strip_think_tags(response.content)
        # Clean up markdown code blocks if present
        if content.startswith("```"):
            content = content.strip("`").replace("json", "").strip()
            
        result_json = json.loads(content)
        
        # Validate result
        if result_json.get("article"):
            app_logger.info(f"target_model_node: extracted {result_json}")
            return {
                "nwc_info": result_json,
                # Optionally set a result message if this node ends the interaction, 
                # but typically this information is passed to a summarizer or another node.
                # The user said "pass info to summarizer".
                # We can also start forming a textual response if needed, but the primary goal is passing nwc_info.
                "result": f"Found target model for {result_json['article']}: {result_json['model']} (Pipeline: {result_json['pipeline']})"
            }
        else:
            app_logger.warning("target_model_node: Could not identifier article/model in query.")
            return {
                 "nwc_info": {},
                 "result": "Could not identify a specific target article/model in the configuration based on your query."
            }
            
    except Exception as e:
        app_logger.error(f"target_model_node: Error executing LLM: {e}")
        return {
            "nwc_info": {},
            "result": "Error identifying target model."
        }
