from agent.graph import app
import os
# import ollama
# import agent.nodes as nodes

# models = ollama.list()
cwd = os.getcwd()

# selected_model = None
# if not models:
#     print("No Ollama models found. Please create a model in Ollama and try again.")
#     exit(1)

# print("Available Ollama models:")
# # List models
# for idx, model in enumerate(models.models):
#     print(f"{idx + 1}. {model.model}")

# while selected_model is None:
#     try:
#         choice = int(input("Select a model by number: "))
#         if 1 <= choice <= len(models.models):
#             selected_model = models.models[choice - 1].model
#         else:
#             print("Invalid selection. Please enter a number from the list.")
#     except ValueError:
#         print("Please enter a valid number.")

# nodes.OLLAMA_MODEL = selected_model

groq_key = os.getenv("GROQ_API_KEY")

if not groq_key:
    print("Groq API key not found.")
    groq_key = input("Enter your Groq API key: ").strip()
    
    # Ask if they want to save it
    save = input("Save to .env file for future use? (yes/no): ")
    if save.lower() == "yes":
        with open(".env", "a") as f:
            f.write(f"\nGROQ_API_KEY={groq_key}")
        print("Saved to .env")

os.environ["GROQ_API_KEY"] = groq_key

while True:
    user_input = input("Enter your query (or 'bye' to quit): ")
    if user_input.lower() == "bye":
        print("Goodbye! Have a great day.")
        break

    state = {"text": user_input, "cwd": cwd}
    result = app.invoke(state)
    cwd = result.get("cwd", cwd)
    print(f"DEBUG cmd: {result.get('cmd', 'no cmd')}")
    print(f"Result: {result.get('result', 'Command cancelled.')}")