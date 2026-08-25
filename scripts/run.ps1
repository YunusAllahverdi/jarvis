param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000
)

uvicorn app.main:app --host $HostAddress --port $Port
