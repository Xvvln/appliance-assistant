// Executed through Open WebUI's documented execute event; data comes from the tool.
try {
  return await new Promise((resolve) => {
    if (document.getElementById('jiadian-address-dialog')) {
      resolve({error: '已有地址窗口打开，请先完成或关闭它。'});
      return;
    }
    const previousFocus = document.activeElement;
    const dialog = document.createElement('dialog');
    dialog.id = 'jiadian-address-dialog';
    dialog.setAttribute('aria-labelledby', 'address-heading');
    dialog.dataset.theme = document.documentElement.classList.contains('dark') ? 'dark' : 'light';
    dialog.innerHTML = `
      <style>
        #jiadian-address-dialog { --bg:#fff;--fg:var(--color-gray-900,#171717);--muted:var(--color-gray-600,#525252);--line:rgb(0 0 0 / .06);--soft:rgb(0 0 0 / .035);--field:rgb(0 0 0 / .025);--error:#b42318;color-scheme:light;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:24px;position:fixed;inset:0;margin:auto;height:fit-content;width:min(576px,calc(100vw - 32px));max-height:calc(100dvh - 32px);overflow:auto;padding:24px;box-sizing:border-box;font-family:inherit;font-size:14px;line-height:1.5;box-shadow:none; }
        #jiadian-address-dialog[data-theme=dark] { --bg:var(--color-gray-900,#171717);--fg:var(--color-gray-100,#eee);--muted:var(--color-gray-400,#aaa);--line:rgb(255 255 255 / .06);--soft:rgb(255 255 255 / .05);--field:rgb(255 255 255 / .03);--error:#ffb4ab;color-scheme:dark; }
        #jiadian-address-dialog::backdrop { background:rgb(0 0 0 / .45); }
        #jiadian-address-dialog[data-theme=dark]::backdrop { background:rgb(0 0 0 / .6); }
        #jiadian-address-dialog * { box-sizing:border-box; }
        #jiadian-address-dialog h2 { margin:0;font-size:18px;font-weight:600;line-height:1.5; }
        #jiadian-address-dialog p { margin:6px 0 16px;color:var(--muted);font-size:13px; }
        #jiadian-address-dialog button { min-height:40px;padding:8px 14px;border:0;border-radius:8px;background:var(--soft);color:var(--fg);font:inherit;font-weight:500;cursor:pointer; }
        #jiadian-address-dialog button:hover { background:var(--line); }
        #jiadian-address-dialog button:active { opacity:.8; }
        #jiadian-address-dialog button.primary { background:var(--fg);color:var(--bg); }
        #jiadian-address-dialog button.primary:hover { opacity:.9; }
        #jiadian-address-dialog button:disabled { opacity:.4;cursor:default; }
        #jiadian-address-dialog :focus-visible { outline:2px solid var(--color-blue-500,#3b82f6);outline-offset:2px; }
        #jiadian-address-dialog input[type=radio],#jiadian-address-dialog input[type=checkbox] { width:16px;height:16px;margin:3px 0;accent-color:var(--fg);flex:none; }
        #jiadian-address-dialog textarea { resize:vertical; }
        #jiadian-address-dialog input::placeholder,#jiadian-address-dialog textarea::placeholder { color:var(--muted);opacity:.75; }
        #jiadian-address-dialog [hidden] { display:none !important; }
        @media(max-width:440px) { #jiadian-address-dialog { padding:20px;width:calc(100vw - 24px); } #jiadian-address-dialog button { min-height:44px; } }

        #jiadian-address-dialog .address-toolbar { display:flex;align-items:center;justify-content:space-between;gap:12px;margin:16px 0 8px; }
        #jiadian-address-dialog .address-toolbar span { color:var(--muted);font-size:12px; }
        #jiadian-address-dialog #address-add,#jiadian-address-dialog .address-card button { background:transparent;font-size:13px; }
        #jiadian-address-dialog #address-add:hover,#jiadian-address-dialog .address-card button:hover { background:var(--soft); }
        #jiadian-address-dialog .address-list { display:grid;gap:2px;max-height:40dvh;overflow:auto;padding:2px; }
        #jiadian-address-dialog .address-card { display:flex;gap:8px;align-items:center;border:0;border-radius:8px;padding:12px; }
        #jiadian-address-dialog .address-card:hover,#jiadian-address-dialog .address-card:has(input:checked) { background:var(--soft); }
        #jiadian-address-dialog .address-card label { display:flex;align-items:flex-start;gap:12px;flex:1;min-width:0;cursor:pointer; }
        #jiadian-address-dialog .address-copy { min-width:0;overflow-wrap:anywhere; }
        #jiadian-address-dialog .address-copy strong { display:block;font-weight:500; }
        #jiadian-address-dialog .address-copy small { display:block;color:var(--muted);font-size:12px;margin-top:4px; }
        #jiadian-address-dialog .address-badge { display:inline-block;margin-left:8px;font-size:11px;font-weight:400;color:var(--muted); }
        #jiadian-address-dialog .address-fields { display:grid;grid-template-columns:1fr 1fr;gap:14px; }
        #jiadian-address-dialog .address-fields label { display:grid;gap:6px;font-size:13px; }
        #jiadian-address-dialog .address-fields .full { grid-column:1 / -1; }
        #jiadian-address-dialog .address-fields input,#jiadian-address-dialog textarea { width:100%;min-height:40px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--field);color:var(--fg);font:inherit; }
        #jiadian-address-dialog textarea { min-height:76px; }
        #jiadian-address-dialog .address-fields input[data-invalid=true],#jiadian-address-dialog textarea[data-invalid=true] { border-color:var(--error); }
        #jiadian-address-dialog .address-error { color:var(--error);font-size:12px; }
        #jiadian-address-dialog .address-check { display:flex;gap:8px;align-items:center;min-height:40px;margin-top:8px;font-size:13px; }
        #jiadian-address-dialog .address-footer { display:flex;justify-content:flex-end;gap:8px;margin-top:20px; }
        #jiadian-address-dialog .address-notice { color:var(--muted);font-size:13px;margin-bottom:12px; }
        @media(max-width:440px) { #jiadian-address-dialog .address-fields { grid-template-columns:1fr;gap:12px; } #jiadian-address-dialog .address-card { align-items:flex-start; } }
      </style>
      <h2 id="address-heading">选择收货地址</h2>
      <p id="address-subtitle">选择或新增地址。</p>
      <div class="address-notice" role="status" aria-live="polite"></div>
      <section id="address-picker">
        <div class="address-toolbar"><span id="address-count"></span><button type="button" id="address-add">＋ 新增地址</button></div>
        <div class="address-list" role="radiogroup" aria-label="收货地址"></div>
        <div class="address-footer"><button type="button" data-cancel>取消</button><button type="button" class="primary" id="address-use">使用所选地址</button></div>
      </section>
      <form id="address-form" hidden>
        <div class="address-fields">
          <label>收件人<input name="recipient" autocomplete="name" maxlength="80" required placeholder="姓名或称呼"><span class="address-error"></span></label>
          <label>联系电话（选填）<input name="phone" type="tel" autocomplete="tel" maxlength="40" placeholder="可留空"><span class="address-error"></span></label>
          <label class="full">所在地区<input name="region" autocomplete="address-level2" maxlength="160" required placeholder="例如：浙江省 温州市 鹿城区"><span class="address-error"></span></label>
          <label class="full">详细地址<textarea name="detail" autocomplete="street-address" maxlength="300" required placeholder="街道、小区、楼栋及门牌号"></textarea><span class="address-error"></span></label>
          <label class="full">地址标签（选填）<input name="label" maxlength="40" placeholder="例如：家、公司、父母家"><span class="address-error"></span></label>
        </div>
        <label class="address-check"><input name="is_default" type="checkbox">设为默认地址</label>
        <div class="address-footer"><button type="button" id="address-back">返回</button><button type="submit" class="primary">保存地址</button></div>
      </form>`;
    const $ = (selector) => dialog.querySelector(selector);
    const addresses = addressData.addresses;
    let selectedId = addresses.find(a => a.id === addressData.selected_id)?.id || addresses.find(a => a.is_default)?.id || addresses[0]?.id;
    let editingId = null;
    const finish = (value) => {
      window.removeEventListener('pagehide', onPageHide);
      dialog.close(); dialog.remove();
      if (previousFocus?.isConnected) previousFocus.focus();
      resolve(value);
    };
    const onPageHide = () => finish({action:'cancel'});
    window.addEventListener('pagehide', onPageHide, {once:true});
    dialog.addEventListener('cancel', (event) => {event.preventDefault();finish({action:'cancel'});});
    const picker = () => {
      $('#address-form').hidden = true; $('#address-picker').hidden = false;
      $('#address-heading').textContent = addressData.title || '选择收货地址';
      $('#address-subtitle').textContent = '选择或新增地址。';
      $('.address-notice').hidden = !addressData.notice;
      $('#address-count').textContent = `已保存 ${addresses.length} 个地址`;
      $('.address-list').replaceChildren();
      for (const address of addresses) {
        const card = document.createElement('div');card.className = 'address-card';
        const label = document.createElement('label');
        const radio = document.createElement('input');radio.type='radio';radio.name='saved-address';radio.value=address.id;radio.checked=address.id===selectedId;
        radio.addEventListener('change',()=>{selectedId=address.id;});
        const copy=document.createElement('span');copy.className='address-copy';
        const title=document.createElement('strong');title.textContent=address.recipient + (address.label ? ` · ${address.label}` : '');
        if(address.is_default){const badge=document.createElement('span');badge.className='address-badge';badge.textContent='默认';title.append(badge);}
        const detail=document.createElement('small');detail.textContent=address.region+' '+address.detail;
        copy.append(title,detail);
        if(address.phone){const phone=document.createElement('small');phone.textContent=address.phone;copy.append(phone);}
        label.append(radio,copy);
        const edit=document.createElement('button');edit.type='button';edit.textContent='编辑';edit.setAttribute('aria-label',`编辑${address.label || address.recipient}地址`);edit.onclick=()=>editor(address);
        card.append(label,edit);$('.address-list').append(card);
      }
      $('#address-use').disabled=!addresses.length;
    };
    const editor = (address = {}) => {
      editingId=address.id || null;
      $('#address-picker').hidden=true;$('#address-form').hidden=false;
      $('#address-heading').textContent=addressData.editor_only ? (editingId?'修改地址':'新增地址') : (editingId?'编辑收货地址':'新增收货地址');
      $('#address-subtitle').textContent='保存后可重复使用。';
      $('.address-notice').hidden = !addressData.draft;
      $('#address-form').reset();
      for(const name of ['recipient','phone','region','detail','label']){$(`[name=${name}]`).value=address[name] || '';}
      $('[name=is_default]').checked=Boolean(address.is_default || !addresses.length);
      dialog.querySelectorAll('.address-error').forEach(e=>e.textContent='');
      dialog.querySelectorAll('[data-invalid]').forEach(e=>delete e.dataset.invalid);
      $('[name=recipient]').focus();
    };
    $('#address-add').onclick=()=>editor();
    if(addressData.editor_only)$('#address-back').textContent='取消';
    $('#address-back').onclick=()=>{if(addressData.editor_only){finish({action:'cancel'});return;}picker();$('#address-add').focus();};
    $('[data-cancel]').onclick=()=>finish({action:'cancel'});
    $('#address-use').onclick=()=>finish({action:'select',id:selectedId});
    $('#address-form').addEventListener('focusout',event=>{
      const field=event.target;
      if(!field.matches('input:not([type=checkbox]),textarea'))return;
      const invalid=field.required && !field.value.trim();field.dataset.invalid=String(invalid);
      field.parentElement.querySelector('.address-error').textContent=invalid?'请填写此项':'';
    });
    $('#address-form').onsubmit=(event)=>{
      event.preventDefault();
      const form=new FormData(event.currentTarget);const draft={id:editingId};
      for(const name of ['recipient','phone','region','detail','label'])draft[name]=String(form.get(name)||'').trim();
      if(!draft.recipient || !draft.region || !draft.detail){$('.address-notice').textContent='请填写收件人、所在地区和详细地址。';return;}
      draft.is_default=form.has('is_default');
      event.currentTarget.querySelector('[type=submit]').disabled=true;
      finish({action:'save',address:draft});
    };
    $('.address-notice').textContent=addressData.notice || '';
    document.body.append(dialog);picker();dialog.showModal();
    if(addressData.editor_only || addressData.draft || !addresses.length)editor(addressData.draft || {});
    else (dialog.querySelector('input:checked') || $('#address-add')).focus();
  });
} catch (error) {
  document.getElementById('jiadian-address-dialog')?.remove();
  return {error:'地址表单打开失败：'+String(error)};
}
