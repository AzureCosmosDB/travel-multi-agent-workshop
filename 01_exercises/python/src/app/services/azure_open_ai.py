import json
import os
import re
import logging
from typing import List
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from openai import AzureOpenAI
from dotenv import load_dotenv

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

load_dotenv(override=False)

# Azure OpenAI configuration
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_OPENAI_EMBEDDING_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")

# Initialize Azure credential and token provider
azure_credential = DefaultAzureCredential()
token_provider = get_bearer_token_provider(
    azure_credential, 
    "https://cognitiveservices.azure.com/.default"
)

# ============================================================================
# LangChain Models (for agents)
# ============================================================================

# Initialize LangChain Azure OpenAI chat model
model = AzureChatOpenAI(
    api_version=AZURE_OPENAI_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    azure_deployment=AZURE_OPENAI_DEPLOYMENT,
    azure_ad_token_provider=token_provider,
    temperature=0.7,
    streaming=True,
    # Emit a final usage chunk while streaming so LangChain aggregates real token
    # counts into AIMessage.usage_metadata (otherwise usage is lost under streaming).
    model_kwargs={"stream_options": {"include_usage": True}},
    max_retries=1
)

# Initialize LangChain embeddings model
embeddings_model = AzureOpenAIEmbeddings(
    api_version=AZURE_OPENAI_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    azure_deployment=AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
    azure_ad_token_provider=token_provider
)

# ============================================================================
# Native OpenAI Client (for MCP server)
# ============================================================================

# Initialize native Azure OpenAI client (for MCP server embeddings)
openai_client = AzureOpenAI(
    api_version=AZURE_OPENAI_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    azure_ad_token_provider=token_provider,
)

logger.info(f"Azure OpenAI initialized")
logger.info(f"   Endpoint: {AZURE_OPENAI_ENDPOINT}")
logger.info(f"   Chat Model: {AZURE_OPENAI_DEPLOYMENT}")
logger.info(f"   Embedding Model: {AZURE_OPENAI_EMBEDDING_DEPLOYMENT}")


# ============================================================================
# Agent Functions (for travel_agents.py)
# ============================================================================

def get_model():
    """Return the initialized Azure OpenAI chat model (LangChain)"""
    return model


def get_embeddings_model():
    """Return the initialized Azure OpenAI embeddings model (LangChain)"""
    return embeddings_model


_STOPWORDS = frozenset({
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "it", "they",
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "and", "but", "or", "nor", "not", "so", "yet", "for", "with",
    "about", "between", "through", "during", "before", "after",
    "above", "below", "to", "from", "in", "out", "on", "off", "over",
    "under", "of", "at", "by", "up", "down", "into", "that", "which",
    "who", "whom", "this", "these", "those", "what", "there", "here",
    "when", "where", "why", "how", "all", "each", "every", "both",
    "few", "more", "most", "other", "some", "such", "no", "just",
    "than", "too", "very", "also", "only", "then", "if", "else",
    "find", "get", "show", "recommend", "want", "like", "prefer",
    "help", "tell", "give", "make", "let", "please", "hi", "hello",
    "day", "trip", "travel", "plan", "looking", "going", "things",
})


def extract_keywords(text: str, max_keywords: int = 5) -> List[str]:
    """
    Extract keywords from text using simple NLP (no LLM call).
    Filters stopwords and returns the most meaningful terms.
    """
    try:
        words = re.findall(r"[a-zA-Z\-]{3,}", text.lower())
        seen = set()
        keywords = []
        for w in words:
            if w not in _STOPWORDS and w not in seen:
                seen.add(w)
                keywords.append(w)
            if len(keywords) >= max_keywords:
                break
        return keywords
    except Exception as e:
        logger.error(f"Error extracting keywords: {e}")
        return []


# ============================================================================
# MCP Server Functions (for mcp_http_server.py)
# ============================================================================

def generate_embedding(text: str) -> List[float]:
    """
    Generate embedding vector for the given text using Azure OpenAI.
    Works with both LangChain model and native OpenAI client.
    
    Args:
        text: Text to generate embedding for
        
    Returns:
        List of floats representing the embedding vector
    """
    try:
        logger.debug(f"Generating embedding for text: {text[:100]}...")
        response = openai_client.embeddings.create(
            input=text,
            model=AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
            dimensions=1024,
        )
        json_response = response.model_dump_json(indent=2)
        parsed_response = json.loads(json_response)
        embedding = parsed_response['data'][0]['embedding']
        logger.debug(f"Generated embedding with dimension: {len(embedding)}")
        return embedding

    except Exception as e:
        logger.error(f"Error generating embedding: {e}")
        raise


def get_openai_client():
    """Return the initialized native Azure OpenAI client"""
    return openai_client
