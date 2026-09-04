// Use the same OpenAI-compatible endpoint and model configuration as the
// rest of Article Agent.  The Python entry point loads the repository .env
// before this generated client is called.
client<llm> GPT4o {
  provider openai
  options {
    model env.ARTICLE_AGENT_MODEL
    api_key env.ARTICLE_AGENT_API_KEY
    base_url env.ARTICLE_AGENT_API_BASE_URL
  }
}
