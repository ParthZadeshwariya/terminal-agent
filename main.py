from agent.graph import app
import os

cwd = os.getcwd()

while True:
    user_input = input("Enter your query (or 'bye' to quit): ")
    if user_input.lower() == "bye":
        print("Goodbye! Have a great day.")
        break

    state = {"text": user_input, "cwd": cwd}
    result = app.invoke(state)
    cwd = result.get("cwd", cwd)
    print(f"Result: {result.get('result', 'Command cancelled.')}")