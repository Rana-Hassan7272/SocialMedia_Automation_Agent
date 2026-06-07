"""
Complete End-to-End Demo.
Full pipeline: Intent → Research → Filter → Summarize → Draft → Review → Publish
"""

from src.agents import (
    IntentAgent, ResearchAgent, FilteringAgent,
    SummarizationAgent, DraftingAgent, PublishingAgent
)
from src.database import DatabaseManager
from src.utils import RedditClient, TwitterClient
from src.workflow.state import create_initial_state

print("🚀 COMPLETE SOCIAL MEDIA AUTOMATION PIPELINE\n")
print("=" * 70)

# Initialize all components
db = DatabaseManager()
reddit_client = RedditClient()
twitter_client = TwitterClient.from_legacy_env()

intent_agent = IntentAgent(db_manager=db)
research_agent = ResearchAgent(db_manager=db, reddit_client=reddit_client)
filtering_agent = FilteringAgent(db_manager=db, top_k=5)
summarization_agent = SummarizationAgent(db_manager=db)
drafting_agent = DraftingAgent(db_manager=db)
publishing_agent = PublishingAgent(db_manager=db, twitter_client=twitter_client)

# User query
query = input("\n📝 Enter your query (or press Enter for default): ").strip()
if not query:
    query = "What's happening in AI today?"

print(f"\n🎯 Query: \"{query}\"\n")
print("=" * 70)

# Create workflow
workflow = db.create_workflow(query)
workflow_id = workflow.id
state = create_initial_state(query, workflow_id)

# STEP 1: Intent Understanding
print("\n📍 STEP 1: Intent Understanding")
print("-" * 70)
state = intent_agent.process(state)
print(f"✅ Topic: {state['topic']}, Scope: {state['scope']}, Tone: {state['tone']}")

# STEP 2: Research
print("\n📍 STEP 2: Research (Reddit)")
print("-" * 70)
state = research_agent.process(state)
print(f"✅ Found {len(state.get('raw_tweets', []))} posts")

# STEP 3: Filter
print("\n📍 STEP 3: Filtering & Ranking")
print("-" * 70)
state = filtering_agent.process(state)
print(f"✅ Filtered to {len(state.get('filtered_tweets', []))} top posts")

# STEP 4: Summarize
print("\n📍 STEP 4: Summarization")
print("-" * 70)
state = summarization_agent.process(state)
print(f"✅ Generated insights")

# STEP 5: Draft
print("\n📍 STEP 5: Drafting")
print("-" * 70)
state = drafting_agent.process(state)
print(f"✅ Created draft ({len(state.get('draft_content', ''))} chars)")

# STEP 6: Human Review
print("\n📍 STEP 6: Human Review")
print("-" * 70)
state = publishing_agent.request_human_review(state)

# Get human decision
print("\n🤔 What would you like to do?")
print("   1. Approve and publish")
print("   2. Request revision")
print("   3. Reject")

choice = input("\nEnter choice (1-3): ").strip()

if choice == "1":
    # STEP 7: Publish
    print("\n📍 STEP 7: Publishing")
    print("-" * 70)
    state = publishing_agent.handle_approval(state)
    
    if state.get("published"):
        print("\n" + "=" * 70)
        print("🎉 SUCCESS! Post published to Twitter/X")
        print(f"🔗 {state.get('tweet_url', 'N/A')}")
        print("=" * 70)
    else:
        print("\n❌ Publishing failed - check Twitter API credentials")

elif choice == "2":
    feedback = input("\n💬 Enter revision feedback: ").strip()
    state = publishing_agent.handle_revision_request(state, feedback)
    
    # Create revision
    print("\n📍 Creating Revision")
    print("-" * 70)
    state = drafting_agent.create_revision(state, feedback)
    
    print(f"\n✅ Revision created!")
    print(f"\n📱 REVISED TWEET:")
    print("-" * 70)
    print(state.get('draft_content', ''))
    print("-" * 70)
    print("\n💡 You can now approve or request another revision")

elif choice == "3":
    reason = input("\n💬 Enter rejection reason (optional): ").strip()
    state = publishing_agent.handle_rejection(state, reason)
    print("\n✅ Draft rejected and workflow closed")

else:
    print("\n⚠️  Invalid choice - workflow paused")

print("\n" + "=" * 70)
print(f"✅ Workflow #{workflow_id} complete")
print(f"📊 Check database for full details")
print("=" * 70)
