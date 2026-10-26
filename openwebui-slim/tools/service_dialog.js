// Native Open WebUI execute event: suspend this tool until the user submits or cancels.
try {
  return await new Promise(resolve => {
    if (document.getElementById('jiadian-service-dialog')) {
      resolve({error: '已有售后窗口打开，请先完成或关闭它。'});return;
    }
    const previousFocus = document.activeElement;
    const dialog = document.createElement('dialog');
    dialog.id = 'jiadian-service-dialog';
    dialog.setAttribute('aria-labelledby', 'service-heading');
    dialog.dataset.theme = document.documentElement.classList.contains('dark') ? 'dark' : 'light';
    dialog.innerHTML = `
      <style>
        #jiadian-service-dialog { --bg:#fff;--fg:var(--color-gray-900,#171717);--muted:var(--color-gray-600,#525252);--line:rgb(0 0 0 / .06);--soft:rgb(0 0 0 / .035);--field:rgb(0 0 0 / .025);--error:#b42318;color-scheme:light;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:24px;position:fixed;inset:0;margin:auto;height:fit-content;width:min(576px,calc(100vw - 32px));max-height:calc(100dvh - 32px);overflow:auto;padding:24px;box-sizing:border-box;font-family:inherit;font-size:14px;line-height:1.5;box-shadow:none; }
        #jiadian-service-dialog[data-theme=dark] { --bg:var(--color-gray-900,#171717);--fg:var(--color-gray-100,#eee);--muted:var(--color-gray-400,#aaa);--line:rgb(255 255 255 / .06);--soft:rgb(255 255 255 / .05);--field:rgb(255 255 255 / .03);--error:#ffb4ab;color-scheme:dark; }
        #jiadian-service-dialog::backdrop { background:rgb(0 0 0 / .45); }
        #jiadian-service-dialog[data-theme=dark]::backdrop { background:rgb(0 0 0 / .6); }
        #jiadian-service-dialog * { box-sizing:border-box; }
        #jiadian-service-dialog h2 { margin:0;font-size:18px;font-weight:600;line-height:1.5; }
        #jiadian-service-dialog p { margin:6px 0 16px;color:var(--muted);font-size:13px; }
        #jiadian-service-dialog button { min-height:40px;padding:8px 14px;border:0;border-radius:8px;background:var(--soft);color:var(--fg);font:inherit;font-weight:500;cursor:pointer; }
        #jiadian-service-dialog button:hover { background:var(--line); }
        #jiadian-service-dialog button:active { opacity:.8; }
        #jiadian-service-dialog button.primary { background:var(--fg);color:var(--bg); }
        #jiadian-service-dialog button.primary:hover { opacity:.9; }
        #jiadian-service-dialog button:disabled { opacity:.4;cursor:default; }
        #jiadian-service-dialog :focus-visible { outline:2px solid var(--color-blue-500,#3b82f6);outline-offset:2px; }
        #jiadian-service-dialog input[type=radio],#jiadian-service-dialog input[type=checkbox] { width:16px;height:16px;margin:3px 0;accent-color:var(--fg);flex:none; }
        #jiadian-service-dialog textarea { resize:vertical; }
        #jiadian-service-dialog input::placeholder,#jiadian-service-dialog textarea::placeholder { color:var(--muted);opacity:.75; }
        #jiadian-service-dialog [hidden] { display:none !important; }
        @media(max-width:440px) { #jiadian-service-dialog { padding:20px;width:calc(100vw - 24px); } #jiadian-service-dialog button { min-height:44px; } }

        #jiadian-service-dialog .cards { display:grid;gap:2px;max-height:35dvh;overflow:auto;padding:2px;margin:12px 0 6px; }
        #jiadian-service-dialog .card { display:flex;align-items:flex-start;gap:12px;padding:12px;border:0;border-radius:8px;cursor:pointer; }
        #jiadian-service-dialog .card:hover,#jiadian-service-dialog .card:has(input:checked) { background:var(--soft); }
        #jiadian-service-dialog .card span { min-width:0;overflow-wrap:anywhere; }
        #jiadian-service-dialog strong { display:block;font-weight:500; }
        #jiadian-service-dialog small { display:block;color:var(--muted);font-size:12px;margin-top:3px; }
        #jiadian-service-dialog #external-choice { border-top:1px solid var(--line);padding-top:6px; }
        #jiadian-service-dialog .field { display:grid;gap:6px;font-size:13px;margin-top:14px; }
        #jiadian-service-dialog .field input,#jiadian-service-dialog textarea,#jiadian-service-dialog select { width:100%;min-height:40px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--field);color:var(--fg);font:inherit; }
        #jiadian-service-dialog textarea { min-height:80px; }
        #jiadian-service-dialog .row { display:grid;grid-template-columns:1fr 1fr;gap:14px; }
        #jiadian-service-dialog .error { color:var(--error);font-size:12px; }
        #jiadian-service-dialog [aria-invalid=true] { border-color:var(--error); }
        #jiadian-service-dialog .footer { display:flex;justify-content:flex-end;gap:8px;margin-top:20px; }
        @media(max-width:440px) { #jiadian-service-dialog .row { grid-template-columns:1fr;gap:0; } }
      </style>
      <h2 id="service-heading"></h2>
      <p id="service-subtitle"></p>
      <form>
        <section id="service-picker" role="radiogroup" aria-label="需要售后的家电"><div class="cards"></div><div id="external-choice"></div>
          <label class="field" id="external-model" hidden>完整产品型号<input name="model" maxlength="100" placeholder="查看机身铭牌，例如 XQG…"><small>其他渠道购买也可咨询。尚不清楚型号时可取消，找到铭牌后再继续。</small><span class="error" aria-live="polite"></span></label>
        </section>
        <label class="field" id="issue-field"><span id="service-issue-label">故障现象</span><textarea name="issue" maxlength="2000" required placeholder="例如：屏幕显示什么代码，在哪个步骤出现，已尝试什么"></textarea><span class="error" aria-live="polite"></span></label>
        <section class="row" id="order-fields" hidden>
          <label class="field">数量<input name="quantity" type="number" min="1" step="1" aria-label="数量"></label>
          <label class="field">服务方式<select name="service" aria-label="服务方式"></select></label>
        </section>
        <section class="row" id="service-appointment" hidden>
          <label class="field">期望上门日期<select name="date" aria-label="期望上门日期"></select></label>
          <label class="field">期望上门时段<select name="slot" aria-label="期望上门时段"></select></label>
        </section>
        <div class="footer"><button type="button" id="service-cancel">取消</button><button type="submit" class="primary" id="service-next"></button></div>
      </form>`;
    const $ = selector => dialog.querySelector(selector);
    const selecting = serviceData.mode === 'select';
    const recordPicking = serviceData.mode === 'record-select';
    const orderEditing = serviceData.mode === 'order-edit';
    let selected = '';
    let settled = false;
    const finish = value => {
      if(settled)return;settled=true;
      window.removeEventListener('pagehide', onPageHide);
      dialog.close();dialog.remove();
      if(previousFocus?.isConnected)previousFocus.focus();
      resolve(value);
    };
    const onPageHide = () => finish({action:'cancel'});
    window.addEventListener('pagehide',onPageHide,{once:true});
    dialog.addEventListener('cancel',event=>{event.preventDefault();finish({action:'cancel'});});
    $('#service-cancel').onclick=()=>finish({action:'cancel'});
    $('[name=issue]').value=serviceData.issue || '';
    if(recordPicking || orderEditing){
      $('#issue-field').hidden=true;$('[name=issue]').required=false;
    }
    if(selecting || recordPicking){
      if(recordPicking)$('#service-picker').setAttribute('aria-label',serviceData.title);
      $('#service-heading').textContent=recordPicking?serviceData.title:'哪台家电需要帮助？';
      $('#service-subtitle').textContent=recordPicking?'选择要办理的记录。':'选择本次咨询的家电，暂不提交报修。';
      $('#service-issue-label').textContent='想咨询什么？';
      $('[name=issue]').placeholder='例如：首次使用、程序选择，或遇到的故障现象';
      $('#service-next').textContent=recordPicking?'继续':'确认家电，继续咨询';$('#service-next').disabled=true;
      const choices=recordPicking?serviceData.records:[...serviceData.orders.map(o=>({id:o.order_id,title:o.model,
        lines:[`订单 ${o.order_id} · ${o.quantity} 台`, `下单 ${String(o.created_at).replace('T',' ').slice(0,16)} · ${o.status}`,o.delivery_address]})),
        {id:'external',title:'不是这些 / 其他渠道购买',lines:['填写机身铭牌上的完整型号']}];
      for(const choice of choices){
        const card=document.createElement('label');card.className='card';
        const input=document.createElement('input');input.type='radio';input.name='appliance';input.value=choice.id;
        const copy=document.createElement('span');const title=document.createElement('strong');title.textContent=choice.title;copy.append(title);
        for(const line of choice.lines){const detail=document.createElement('small');detail.textContent=line;copy.append(detail);}
        input.onchange=()=>{selected=choice.id;$('#service-next').disabled=false;$('#external-model').hidden=selected!=='external';$('[name=model]').required=selected==='external';if(selected==='external')$('[name=model]').focus();};
        card.append(input,copy);$(choice.id==='external'?'#external-choice':'.cards').append(card);
      }
    }else{
      $('#service-heading').textContent=orderEditing?'修改订单':(serviceData.title || '填写报修信息');
      $('#service-subtitle').textContent=`${serviceData.model} · ${orderEditing?'修改后还需确认。':'选择预约时间。'}`;
      $('#service-picker').hidden=true;$('#service-appointment').hidden=false;$('#service-next').textContent=orderEditing?'下一步：选择收货地址':'下一步：选择上门地址';
      if(orderEditing){
        $('#order-fields').hidden=false;$('[name=quantity]').required=true;
        $('[name=quantity]').value=serviceData.draft.quantity;
        for(const value of serviceData.services){const option=document.createElement('option');option.value=value;option.textContent=value;$('[name=service]').append(option);}
        $('[name=service]').value=serviceData.draft.service;
        $('[name=date]').parentElement.firstChild.textContent='配送日期';$('[name=date]').setAttribute('aria-label','配送日期');
        $('[name=slot]').parentElement.firstChild.textContent='配送时段';$('[name=slot]').setAttribute('aria-label','配送时段');
      }
      for(const [name,values] of [['date',serviceData.dates],['slot',serviceData.slots]]){
        for(const value of values){const option=document.createElement('option');option.value=value;option.textContent=value;$(`[name=${name}]`).append(option);}
        if(values.includes(serviceData.draft?.[name]))$(`[name=${name}]`).value=serviceData.draft[name];
      }
    }
    const validate=field=>{
      const invalid=field.required && !field.value.trim();
      field.setAttribute('aria-invalid',String(invalid));
      const error=field.parentElement.querySelector('.error');if(error)error.textContent=invalid?'请填写此项':'';
      return !invalid;
    };
    $('form').addEventListener('focusout',event=>{if(event.target.matches('textarea,input[name=model]'))validate(event.target);});
    $('form').onsubmit=event=>{
      event.preventDefault();
      if(recordPicking){if(selected)finish({action:'record-select',id:selected});return;}
      if(orderEditing){
        const quantity=Number($('[name=quantity]').value);
        if(!Number.isInteger(quantity)||quantity<1){$('[name=quantity]').reportValidity();return;}
        finish({action:'order-edit',quantity,date:$('[name=date]').value,slot:$('[name=slot]').value,service:$('[name=service]').value});return;
      }
      if(!validate($('[name=issue]'))){$('[name=issue]').focus();return;}
      if(selecting && !selected)return;
      if(selecting && selected==='external' && !validate($('[name=model]'))){$('[name=model]').focus();return;}
      $('#service-next').disabled=true;
      const issue=$('[name=issue]').value.trim();
      finish(selecting?{action:'select',source:selected==='external'?'external':'order',order_id:selected,model:$('[name=model]').value.trim(),issue}
        :{action:'appointment',issue,date:$('[name=date]').value,slot:$('[name=slot]').value});
    };
    document.body.append(dialog);dialog.showModal();
    (selecting || recordPicking?$('input[type=radio]'):(orderEditing?$('[name=quantity]'):$('[name=issue]')))?.focus();
  });
}catch(error){
  document.getElementById('jiadian-service-dialog')?.remove();
  return {error:'售后窗口打开失败：'+String(error)};
}
