"""
Demo using LangGraph workflow orchestration.
Shows the complete system running through the graph.
"""

from src.workflow.graph import WorkflowGraph
from src.database import DatabaseManager
from src.utils import RedditClient, TwitterClient

print("🎯 LangGraph Workflow Demo\n")
print("=" * 70)

# Initialize components
db = DatabaseManager()
reddit_client = RedditClient()
twitter_client = TwitterClient.from_legacy_env()

# Create workflow graph
workflow_graph = WorkflowGraph(
    db_manager=db,
    reddit_client=reddit_client,
    twitter_client=twitter_client
)

# Get user query
query = input("\n📝 Enter your query (or press Enter for default): ").strip()
if not query:
    query = "What's happening in AI today?"

print(f"\n🎯 Query: \"{query}\"\n")

# Run the workflow through LangGraph
try:
    final_state = workflow_graph.run(query)
    
    print("\n📊 Final State:")
    print(f"   Topic: {final_state.get('topic')}")
    print(f"   Posts found: {len(final_state.get('raw_tweets', []))}")
    print(f"   Filtered: {len(final_state.get('filtered_tweets', []))}")
    print(f"   Draft: {final_state.get('draft_content', 'N/A')[:100]}...")
    
    if final_state.get('published'):
        print(f"\n🎉 Published to Twitter/X!")
        print(f"   🔗 {final_state.get('tweet_url')}")
    
except Exception as e:
    print(f"\n❌ Error: {str(e)}")

print("\n" + "=" * 70)
print("✅ LangGraph workflow complete!")
