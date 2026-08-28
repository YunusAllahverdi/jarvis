import React, { type InputHTMLAttributes } from 'react';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  // additional props here
}

export const Input: React.FC<InputProps> = ({ className = '', ...props }) => {
  return (
    <input className={`input-field ${className}`.trim()} {...props} />
  );
};
