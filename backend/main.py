from fastapi import FastAPI

# 1. Create the app instance (the CLI looks for this variable name)
app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Hello from backend!"}

# You can keep your main function for local testing if you want,
# but FastAPI doesn't need it to run the server.

def main():
    print("This runs only if you execute 'python main.py' directly")

if __name__ == "__main__":
    main()