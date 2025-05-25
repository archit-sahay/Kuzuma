import socketio


sio = None


def create_socketio_app():
    global sio
    try:
        if sio is None:
            print('Creating Socket IO App')
            sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=[])
        return sio
    except Exception as e:
        print(f"Error while creating socketio app: ", e.__traceback__)
        raise RuntimeError("Error while getting socketio client instance")
