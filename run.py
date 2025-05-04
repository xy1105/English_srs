from app import create_app

app = create_app()

if __name__ == '__main__':
    # debug=True 会根据 FLASK_ENV=development 自动开启
    # host='0.0.0.0' 允许局域网访问
    app.run(host='0.0.0.0', port=5000)