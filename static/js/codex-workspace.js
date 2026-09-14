(() => {
  const $ = id => document.getElementById('cx-' + id);
  let selected = null, current = null, timer = null;
  const draftKey='respectaso-codex-draft-v1';
  const fields=['mode','brief','seed','country','promoted_app_id','competitor_app_id'];
  const names={research:'Keyword research',competitor:'Competitor analysis',metadata:'Metadata review'};
  function saveDraft(){try{const data={};for(const key of fields)data[key]=$('form').elements[key].value;localStorage.setItem(draftKey,JSON.stringify(data));}catch{}}
  function fillDraft(data){for(const key of fields)if(typeof data[key]==='string')$('form').elements[key].value=data[key];}
  try{fillDraft(JSON.parse(localStorage.getItem(draftKey)||'{}'));}catch{}
  $('mode').addEventListener('change',()=>{$('app-options').open=$('mode').value==='competitor';});
  $('form').addEventListener('input',saveDraft);$('form').addEventListener('change',saveDraft);
  $('clear').onclick=()=>{$('form').reset();saveDraft();$('brief').focus();};
  $('reuse').onclick=()=>{if(current){fillDraft(current);saveDraft();$('app-options').open=!!current.promoted_app_id||!!current.competitor_app_id;$('brief').focus();}};
  const csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;
  async function api(url, data) {
    const options = data ? {method:'POST', headers:{'X-CSRFToken':csrf}, body:data} : {};
    const response = await fetch(url, options);
    let body;try{body=await response.json();}catch{throw new Error('The app is restarting or unavailable. Retry in a moment.');}
    if (!response.ok) throw new Error(body.error || 'Request failed. Please retry.');
    return body;
  }
  function add(tag, text) {const node=document.createElement(tag); node.textContent=text; $('result').append(node); return node;}
  function render(row) {
    const finished = current?.id===row.id && current.status!==row.status && ['completed','failed'].includes(row.status);
    current=row; $('heading').textContent=names[row.mode]||'Analysis';
    $('reuse').hidden=false;$('copy').textContent='Copy report';
    if(finished)history().catch(()=>{});
    let elapsed='';if(row.started_at){const seconds=Math.max(0,Math.round(((row.finished_at?Date.parse(row.finished_at):Date.now())-Date.parse(row.started_at))/1000));elapsed=` · ${Math.floor(seconds/60)}m ${seconds%60}s`;}
    $('progress').textContent=(row.error || row.progress || row.status)+elapsed;
    $('progress').classList.toggle('cx-error', row.status==='failed');
    $('result').replaceChildren();
    $('copy').hidden=row.status!=='completed';$('research').hidden=row.status!=='completed'||!row.report?.keywords?.length;
    $('retry').hidden=row.status!=='failed';
    $('evidence').hidden=!row.evidence.length&&!row.discovery?.snapshots?.length;
    $('evidence-text').textContent=JSON.stringify({scored:row.evidence,apple:row.discovery||{}},null,2);
    if (row.status==='completed') {
      const r=row.report;
      if(r.research_summary) {const s=r.research_summary;add('p',`${s.apple_candidates} Apple candidates · ${s.scored_keywords} scored keywords · refined with Codex`);}
      add('div',r.analysis).className='cx-report';
      if(r.validation) add('p',r.validation.passed ? 'Metadata checks passed (lengths, spacing and duplication).' : 'Metadata needs attention: '+r.validation.issues.join('; '));
      if(r.unscored_keywords?.length) add('p','Not measured: '+r.unscored_keywords.join(', '));
      if(row.evidence.length){
        add('h3','Scored research');
        const wrapper=add('div','');wrapper.className='cx-table';const table=document.createElement('table');wrapper.append(table);table.style.width='100%';table.style.fontSize='12px';
        const head=document.createElement('tr');for(const title of ['Keyword','Source','Popularity','Difficulty','Opportunity']){const th=document.createElement('th');th.textContent=title;th.style.textAlign='left';head.append(th);}table.append(head);
        for(const item of row.evidence){const tr=document.createElement('tr');for(const value of [item.keyword,({apple:'Apple',codex:'Codex',user_seed:'Your seed'})[item.candidate_source]||'Research',`${item.popularity ?? '—'} (${item.popularity_source==='apple'?'Apple':'estimate'})`,item.difficulty,item.opportunity]){const td=document.createElement('td');td.textContent=value;td.style.padding='6px 3px';tr.append(td);}table.append(tr);}
      }
      add('h3',r.research_summary ? 'Recommended keywords' : 'Suggested keywords · not yet scored'); add('p',r.keywords.join(', '));
      for(const [key,label,limit] of [['title','Title',30],['subtitle','Subtitle',30],['keyword_field','Keyword field',100]]) {
        add('h3',`${label} · ${[...r[key]].length}/${limit}`); add('code',r[key]);
        const copy=add('button',`Copy ${label.toLowerCase()}`);copy.className='secondary';copy.onclick=async()=>{try{await navigator.clipboard.writeText(r[key]);copy.textContent='Copied';}catch{$('error').textContent='Select the field text to copy it.';}};
      }
      if(r.cautions.length){add('h3','Things to check'); const list=add('ul',''); for(const c of r.cautions){const li=document.createElement('li');li.textContent=c;list.append(li);}}
    }
    clearTimeout(timer);
    if(['running','queued'].includes(row.status)) timer=setTimeout(()=>select(row.id),2500);
  }
  async function select(id) {selected=id;try {const row=await api(`/codex/runs/${id}/`);if(selected===id)render(row);}catch(e){$('error').textContent=e.message;timer=setTimeout(()=>select(id),5000);}}
  async function history() {const data=await api('/codex/runs/');$('history').replaceChildren();for(const row of data.runs){const b=document.createElement('button');b.textContent=`${names[row.mode]||row.mode} · ${row.status} — ${row.brief.slice(0,55)}`;b.onclick=()=>select(row.id);$('history').append(b);}return data.runs;}
  $('form').onsubmit=async e=>{e.preventDefault();$('error').textContent='';$('submit').disabled=true;try{const row=await api('/codex/runs/',new FormData($('form')));selected=row.id;render(row);$('heading').focus();$('heading').scrollIntoView({block:'start'});await history();}catch(e){$('error').textContent=e.message;}finally{$('submit').disabled=false;}};
  $('retry').onclick=async()=>{try{render(await api(`/codex/runs/${current.id}/retry/`,new FormData()));await history();}catch(e){$('error').textContent=e.message;}};
  $('copy').onclick=async()=>{try{await navigator.clipboard.writeText($('result').innerText);$('copy').textContent='Copied';}catch(e){$('error').textContent='Select the report text to copy it.';}};
  $('research').onclick=async()=>{if(!current)return;const data=new FormData();data.set('keywords',current.report.keywords.join(','));data.set('countries',current.country);try{await api('/search/',data);window.location.href='/';}catch(e){$('error').textContent=e.message;}};
  (async()=>{try{const state=await api('/codex/status/');$('connection').textContent=state.message;$('apple').textContent=state.apple?.message||'Apple Ads status unavailable';$('submit').disabled=!state.connected;const rows=await history();if(rows.length)await select(rows[0].id);}catch(e){$('connection').textContent=e.message;}})();
})();
