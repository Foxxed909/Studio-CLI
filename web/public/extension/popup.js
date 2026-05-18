document.getElementById('shareScreen').addEventListener('click', async () => {
  chrome.tabs.query({active: true, currentWindow: true}, function(tabs) {
    if (tabs[0]) {
      chrome.tabs.sendMessage(tabs[0].id, {action: "share_screen"});
      document.getElementById('status').innerText = "Status: Sharing screen...";
    }
  });
});

document.getElementById('takeAction').addEventListener('click', () => {
  document.getElementById('status').innerText = "Status: Executing AI action...";
});
