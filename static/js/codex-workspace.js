(() => {
  const $ = id => document.getElementById('cx-' + id);
  let selected = null, current = null, timer = null;
  const csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;
  async function api(url, data) {
    const options = data ? {method:'POST', headers:{'X-CSRFToken':csrf}, body:data} : {};
    const response = await fetch(url, options);
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || 'Request failed. Please retry.');
    return body;
  }
  function add(tag, text) {const node=document.createElement(tag); node.textContent=text; $('result').append(node); return node;}
  function render(row) {
    current=row; $('heading').textContent=row.mode[0].toUpperCase()+row.mode.slice(1)+' analysis';
    $('progress').textContent=row.error || row.progress || row.status;
    $('progress').classList.toggle('cx-error', row.status==='failed');
    $('result').replaceChildren();
    $('copy').hidden=$('research').hidden=row.status!=='completed';
    $('retry').hidden=row.status!=='failed';
    $('evidence').hidden=!row.evidence.length;
    $('evidence-text').textContent=JSON.stringify(row.evidence,null,2);
    if (row.status==='completed') {
      const r=row.report; add('div',r.analysis).className='cx-report';
      add('h3','Suggested keywords · not yet scored'); add('p',r.keywords.join(', '));
      for(const [key,label,limit] of [['title','Title',30],['subtitle','Subtitle',30],['keyword_field','Keyword field',100]]) {
        add('h3',`${label} · ${r[key].length}/${limit}`); add('code',r[key]);
      }
      if(r.cautions.length){add('h3','Things to check'); const list=add('ul',''); for(const c of r.cautions){const li=document.createElement('li');li.textContent=c;list.append(li);}}
    }
    clearTimeout(timer);
    if(['running','queued'].includes(row.status)) timer=setTimeout(()=>select(row.id),2500);
  }
  async function select(id) {selected=id;try {const row=await api(`/codex/runs/${id}/`);if(selected===id)render(row);}catch(e){$('error').textContent=e.message;}}
  async function history() {const data=await api('/codex/runs/');$('history').replaceChildren();for(const row of data.runs){const b=document.createElement('button');b.textContent=`${row.mode} · ${row.status} — ${row.brief.slice(0,55)}`;b.onclick=()=>select(row.id);$('history').append(b);}return data.runs;}
  $('form').onsubmit=async e=>{e.preventDefault();$('error').textContent='';$('submit').disabled=true;try{const row=await api('/codex/runs/',new FormData($('form')));selected=row.id;render(row);await history();}catch(e){$('error').textContent=e.message;}finally{$('submit').disabled=false;}};
  $('retry').onclick=async()=>{try{render(await api(`/codex/runs/${current.id}/retry/`,new FormData()));await history();}catch(e){$('error').textContent=e.message;}};
  $('copy').onclick=async()=>{try{await navigator.clipboard.writeText($('result').innerText);$('copy').textContent='Copied';}catch(e){$('error').textContent='Select the report text to copy it.';}};
  $('research').onclick=async()=>{if(!current)return;const data=new FormData();data.set('keywords',current.report.keywords.join(','));data.set('countries',current.country);try{await api('/search/',data);window.location.href='/';}catch(e){$('error').textContent=e.message;}};
  (async()=>{try{const state=await api('/codex/status/');$('connection').textContent=state.message;$('submit').disabled=!state.connected;const rows=await history();if(rows.length)await select(rows[0].id);}catch(e){$('connection').textContent=e.message;}})();
})();
