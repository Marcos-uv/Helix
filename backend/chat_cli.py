import requests

API_URL = "http://127.0.0.1:8000/chat"

print("Bem-vindo ao chat com Helix! Digite 'sair' para encerrar a conversa.")

while True:
    user_input = input("Você: ")

    if user_input.lower() in ["sair", "exit"]:
        print("Encerrando helix...")
        break

    response = requests.post(API_URL, json={
        "message": user_input
    })

    if response.status_code == 200:
        data = response.json()
        print(f"Helix: {data['response']}\n")
    else:
        print("Erro ao conectar com o Helix\n")