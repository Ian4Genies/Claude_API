from src import stream_message

if __name__ == "__main__":
    for chunk in stream_message("Count from 1 to 5, one number per line."):
        print(chunk, end="", flush=True)
    print()
