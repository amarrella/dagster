import { DocSearchModal, useDocSearchKeyboardEvents } from "@docsearch/react";
import { useCallback, useEffect, useRef, useState } from "react";

import Head from "next/head";
import Link from "next/link";
import { createPortal } from "react-dom";
import { useRouter } from "next/router";

const ACTION_KEY_DEFAULT = ["Ctrl ", "Control"];
const ACTION_KEY_APPLE = ["⌘", "Command"];

function Hit({ hit, children }) {
  return (
    <Link href={hit.url}>
      <a>{children}</a>
    </Link>
  );
}

export function Search() {
  const router = useRouter();
  const [isOpen, setIsOpen] = useState(false);
  const searchButtonRef = useRef();
  const [initialQuery, setInitialQuery] = useState(null);
  const [browserDetected, setBrowserDetected] = useState(false);
  const [actionKey, setActionKey] = useState(ACTION_KEY_DEFAULT);

  const onOpen = useCallback(() => {
    setIsOpen(true);
  }, [setIsOpen]);

  const onClose = useCallback(() => {
    setIsOpen(false);
  }, [setIsOpen]);

  const onInput = useCallback(
    (e) => {
      setIsOpen(true);
      setInitialQuery(e.key);
    },
    [setIsOpen, setInitialQuery]
  );

  useDocSearchKeyboardEvents({
    isOpen,
    onOpen,
    onClose,
    onInput,
    searchButtonRef,
  });

  useEffect(() => {
    if (typeof navigator !== "undefined") {
      if (/(Mac|iPhone|iPod|iPad)/i.test(navigator.platform)) {
        setActionKey(ACTION_KEY_APPLE);
      } else {
        setActionKey(ACTION_KEY_DEFAULT);
      }
      setBrowserDetected(true);
    }
  }, []);

  return (
    <>
      <Head>
        <link
          rel="preconnect"
          href={`https://${process.env.NEXT_PUBLIC_ALGOLIA_APP_ID}-dsn.algolia.net`}
          crossOrigin="true"
        />
      </Head>
      <button
        type="button"
        ref={searchButtonRef}
        onClick={onOpen}
        className="group leading-6 font-medium flex items-center space-x-3 sm:space-x-4 text-gray-500 hover:text-gray-600 transition-colors duration-200 w-full py-2"
      >
        <svg
          width="24"
          height="24"
          fill="none"
          className="text-gray-400 group-hover:text-gray-500 transition-colors duration-200 flex-shrink-0"
        >
          <path
            d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <span>
          Quick search<span className="hidden sm:inline"> for anything</span>
        </span>
        <span
          style={{ opacity: browserDetected ? "1" : "0" }}
          className="hidden sm:block text-gray-400 text-sm leading-5 py-0.5 px-1.5 border border-gray-300 rounded-md"
        >
          <span className="sr-only">Press </span>
          <kbd className="font-sans">
            <abbr title={actionKey[1]} className="no-underline">
              {actionKey[0]}
            </abbr>
          </kbd>
          <span className="sr-only"> and </span>
          <kbd className="font-sans">K</kbd>
          <span className="sr-only"> to search</span>
        </span>
      </button>
      {isOpen &&
        createPortal(
          <DocSearchModal
            initialQuery={initialQuery}
            initialScrollY={window.scrollY}
            searchParameters={{
              distinct: 1,
            }}
            onClose={onClose}
            indexName={process.env.NEXT_PUBLIC_ALGOLIA_INDEX_NAME}
            apiKey={process.env.NEXT_PUBLIC_ALGOLIA_SEARCH_API_KEY}
            appId={process.env.NEXT_PUBLIC_ALGOLIA_APP_ID}
            navigator={{
              navigate({ itemUrl }) {
                setIsOpen(false);
                router.push(itemUrl);
              },
            }}
            hitComponent={Hit}
            transformItems={(items) => {
              return items.map((item) => {
                // We transform the absolute URL into a relative URL to
                // leverage Next's preloading.
                const a = document.createElement("a");
                a.href = item.url;

                const hash = a.hash === "#content-wrapper" ? "" : a.hash;

                return {
                  ...item,
                  url: `${a.pathname}${hash}`,
                };
              });
            }}
          />,
          document.body
        )}
    </>
  );
}
