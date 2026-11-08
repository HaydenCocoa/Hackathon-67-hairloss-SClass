// Local contract stand-in only; contains no real credentials or user records.
const http = require('node:http')
http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost')
  res.setHeader('Content-Type', 'application/json')
  // Simulation path routing consumes /rest before handing the request to us.
  if (req.method !== 'GET' || url.pathname !== '/v1/rooms') {
    res.writeHead(501).end(JSON.stringify({ message: 'Not modeled' }))
  } else if (req.headers.apikey !== 'sb_secret_simulation') {
    res.writeHead(401).end(JSON.stringify({ message: 'Invalid API key' }))
  } else if (url.searchParams.get('select') !== 'id' || url.searchParams.get('limit') !== '1') {
    res.writeHead(400).end(JSON.stringify({ message: 'Expected bounded id query' }))
  } else {
    res.writeHead(200).end('[]')
  }
}).listen(process.env.PORT)
