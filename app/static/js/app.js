// Ask for confirmation before destructive POST actions.
document.addEventListener('submit', function (e) {
    const form = e.target;
    if (form.classList.contains('js-confirm')) {
        if (!window.confirm('Вы уверены? Действие нельзя отменить.')) {
            e.preventDefault();
        }
    }
});
