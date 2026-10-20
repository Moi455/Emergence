//! Exécuteur minimal de futurs : `wgpu` 30 expose `request_adapter`, `enumerate_adapters` et
//! `request_device` comme des futurs ; l'hôte les attend sur le fil courant, sans dépendance de plus.

use std::future::Future;
use std::pin::pin;
use std::sync::Arc;
use std::task::{Context, Poll, Wake, Waker};
use std::thread::{self, Thread};

/// Réveil du fil qui attend.
struct ReveilFil(Thread);

impl Wake for ReveilFil {
    fn wake(self: Arc<Self>) {
        self.0.unpark();
    }
}

/// Attend la fin d'un futur en bloquant le fil courant.
pub(crate) fn attendre<F: Future>(futur: F) -> F::Output {
    let mut futur = pin!(futur);
    let waker = Waker::from(Arc::new(ReveilFil(thread::current())));
    let mut contexte = Context::from_waker(&waker);
    loop {
        match futur.as_mut().poll(&mut contexte) {
            Poll::Ready(valeur) => return valeur,
            Poll::Pending => thread::park(),
        }
    }
}
