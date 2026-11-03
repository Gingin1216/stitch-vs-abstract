import { useTypewriter } from "../lib/useTypewriter";

interface StoryTextProps {
  sentence: string;
}

export function StoryText({ sentence }: StoryTextProps) {
  const visibleText = useTypewriter(sentence);
  const isTyping = visibleText.length < sentence.length;

  return (
    <p className="story-text" aria-label={sentence}>
      <span aria-hidden="true">{visibleText}</span>
      {isTyping ? <span className="type-caret" aria-hidden="true" /> : null}
    </p>
  );
}
