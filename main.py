from agent.graph import app
import os

while True:
    user_input = input("Enter your query (or 'exit' to quit): ")
    if user_input.lower() == "exit":
        break

    state = {"text": user_input, "cwd": os.getcwd()}
    result = app.invoke(state)
    print(f"Result: {result.get('result', 'Command cancelled.')}")