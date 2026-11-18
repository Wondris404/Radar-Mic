// Run from repo root after npm ci --prefix tools --ignore-scripts.
// Git fetches the exact dependency revision; avoids CLI GitHub downloader/proxy issues.
const fs=require('node:fs');
const path=require('node:path');
const os=require('node:os');
const {execFileSync}=require('node:child_process');
const root=path.resolve(__dirname,'..');
const target=path.join(root,'tools/node_modules/pxt-microbit');
const cli=require.resolve('pxt-core/built/pxt.js',{paths:[target]});
const invoke=(role,cmd)=>execFileSync(process.execPath,['-e',`require(${JSON.stringify(cli)}).mainCli(${JSON.stringify(target)},[${JSON.stringify(cmd)}])`],{cwd:path.join(root,'firmware',role),stdio:'inherit'});
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'radar-sonar-'));
try {
  execFileSync('git',['clone','https://github.com/elecfreaks/pxt-sonarbit.git',temporary],{stdio:'inherit'});
  execFileSync('git',['checkout','--detach','3745c29c385dc85a13600d48391ff32e85f0748d'],{cwd:temporary,stdio:'inherit'});
  invoke('aircraft','install');
  fs.cpSync(path.join(root,'firmware/aircraft/pxt_modules'),path.join(root,'firmware/ground/pxt_modules'),{recursive:true});
  fs.cpSync(temporary,path.join(root,'firmware/ground/pxt_modules/sonarbit'),{recursive:true,filter:p=>path.basename(p)!=='.git'});
  fs.mkdirSync(path.join(root,'dist/firmware'),{recursive:true});
  for(const role of ['ground','aircraft']) {
    invoke(role,'build');
    fs.copyFileSync(path.join(root,'firmware',role,'built/binary.hex'),path.join(root,'dist/firmware',`radar-mic-${role}.hex`));
  }
} finally { fs.rmSync(temporary,{recursive:true,force:true}); }
