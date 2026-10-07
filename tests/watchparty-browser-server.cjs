const http=require('http'),fs=require('fs');
const root=require('path').resolve(__dirname,'..');
const rate=8000, count=rate*60, wav=Buffer.alloc(44+count*2);
wav.write('RIFF');wav.writeUInt32LE(36+count*2,4);wav.write('WAVEfmt ',8);wav.writeUInt32LE(16,16);wav.writeUInt16LE(1,20);wav.writeUInt16LE(1,22);wav.writeUInt32LE(rate,24);wav.writeUInt32LE(rate*2,28);wav.writeUInt16LE(2,32);wav.writeUInt16LE(16,34);wav.write('data',36);wav.writeUInt32LE(count*2,40);
http.createServer((req,res)=>{
 if(req.url==='/tone.wav'){
  const range=/bytes=(\d+)-(\d*)/.exec(req.headers.range||'');
  const start=range?Number(range[1]):0, end=range&&range[2]?Math.min(Number(range[2]),wav.length-1):wav.length-1;
  const headers={'Content-Type':'audio/wav','Content-Length':end-start+1,'Accept-Ranges':'bytes'};
  if(range)headers['Content-Range']='bytes '+start+'-'+end+'/'+wav.length;
  res.writeHead(range?206:200,headers);return res.end(wav.subarray(start,end+1));
 }

 const path=req.url==='/watchparty-sync.js'?'/static/js/watchparty-sync.js':req.url==='/'?'/tests/watchparty-browser.html':null;
 if(!path){res.writeHead(404);return res.end();}
 res.setHeader('Content-Type',path.endsWith('.js')?'application/javascript':'text/html');res.end(fs.readFileSync(root+path));
}).listen(5556,'127.0.0.1',()=>console.log('Test media server on 5556'));
