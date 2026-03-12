from agent.graph import app

with open("graph.png", "wb") as f:
    f.write(app.get_graph().draw_mermaid_png())