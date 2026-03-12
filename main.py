from agent.graph import app
import os

while True:
    user_input = input("Enter your query (or 'bye' to quit): ")
    if user_input.lower() == "bye":
        print("Goodbye! Have a great day.")
        break

    state = {"text": user_input, "cwd": os.getcwd()}
    result = app.invoke(state)
    print(f"Result: {result.get('result', 'Command cancelled.')}")